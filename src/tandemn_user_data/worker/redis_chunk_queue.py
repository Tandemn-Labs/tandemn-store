"""Worker-side Redis chunk queue operations.

Workers import this module to pull chunk metadata, renew leases, and mark
chunks complete/failed. It intentionally lives in tandemn_user_data so
workers do not import tandemn_system_data.
"""

from __future__ import annotations

import json
import os
import time

import redis

from tandemn_user_data.core import ChunkLease, ChunkProgress, OutputRef, PayloadRef

DEFAULT_REDIS_URL = "redis://localhost:56379/0"
DEFAULT_LEASE_TTL_SEC = 120
_PREFIX = "chunk:job"


def _meta_key(job_id: str) -> str:
    return f"{_PREFIX}:{job_id}:meta"


def _pending_key(job_id: str) -> str:
    return f"{_PREFIX}:{job_id}:pending"


def _inflight_key(job_id: str) -> str:
    return f"{_PREFIX}:{job_id}:inflight"


def _completed_key(job_id: str) -> str:
    return f"{_PREFIX}:{job_id}:completed"


def _failed_key(job_id: str) -> str:
    return f"{_PREFIX}:{job_id}:failed"


def _chunk_key(job_id: str, chunk_id: str) -> str:
    return f"{_PREFIX}:{job_id}:chunk:{chunk_id}"


_RENEW_LUA = """
local chunk_key = KEYS[1]
local chain_id = ARGV[1]
local new_lease = ARGV[2]

local status = redis.call('HGET', chunk_key, 'status')
local owner = redis.call('HGET', chunk_key, 'chain_id')

if status ~= 'inflight' or owner ~= chain_id then
    return {0, 0}
end

redis.call('HSET', chunk_key, 'lease_until', new_lease)
return {1, new_lease}
"""


class RedisChunkQueueWorker:
    """Worker-side chunk queue client."""

    def __init__(self, redis_url: str | None = None, *, lease_ttl_sec: int = DEFAULT_LEASE_TTL_SEC):
        self.url = redis_url or os.getenv("TANDEMN_REDIS_URL", DEFAULT_REDIS_URL)
        self.lease_ttl_sec = lease_ttl_sec
        self._r = redis.from_url(self.url, decode_responses=True)
        self._renew_script = self._r.register_script(_RENEW_LUA)

    def pull_chunk(self, job_id: str, chain_id: str) -> ChunkLease | None:
        """Claim the next pending chunk for chain_id."""
        chunk_id = self._r.lpop(_pending_key(job_id))
        if chunk_id is None:
            return None

        now = time.time()
        lease_until = now + self.lease_ttl_sec
        pipe = self._r.pipeline(transaction=True)
        pipe.sadd(_inflight_key(job_id), chunk_id)
        pipe.hset(
            _chunk_key(job_id, chunk_id),
            mapping={
                "status": "inflight",
                "chain_id": chain_id,
                "started_at": now,
                "lease_until": lease_until,
            },
        )
        pipe.hgetall(_chunk_key(job_id, chunk_id))
        result = pipe.execute()
        info = result[-1]
        return _lease_from_hash(info)

    def renew_lease(self, job_id: str, chunk_id: str, chain_id: str) -> bool:
        new_lease = time.time() + self.lease_ttl_sec
        renewed, _ = self._renew_script(
            keys=[_chunk_key(job_id, chunk_id)],
            args=[chain_id, new_lease],
        )
        return bool(int(renewed))

    def complete_chunk(self, job_id: str, chunk_id: str, chain_id: str) -> ChunkProgress:
        # Idempotency: already completed means return current progress.
        if self._r.sismember(_completed_key(job_id), chunk_id):
            return self.get_progress(job_id)

        info = self._r.hgetall(_chunk_key(job_id, chunk_id))
        if not info:
            raise KeyError(f"unknown chunk_id={chunk_id!r} for job_id={job_id!r}")
        if info.get("status") != "inflight" or info.get("chain_id") != chain_id:
            raise PermissionError(f"chain_id={chain_id!r} does not own chunk_id={chunk_id!r}")

        now = time.time()
        pipe = self._r.pipeline(transaction=True)
        pipe.srem(_inflight_key(job_id), chunk_id)
        pipe.srem(_failed_key(job_id), chunk_id)
        pipe.sadd(_completed_key(job_id), chunk_id)
        pipe.hset(
            _chunk_key(job_id, chunk_id),
            mapping={"status": "completed", "completed_at": now, "lease_until": 0},
        )
        pipe.execute()
        return self.get_progress(job_id)

    def fail_chunk(
        self, job_id: str, chunk_id: str, chain_id: str, reason_code: str
    ) -> ChunkProgress:
        info = self._r.hgetall(_chunk_key(job_id, chunk_id))
        if not info:
            raise KeyError(f"unknown chunk_id={chunk_id!r} for job_id={job_id!r}")
        if info.get("status") != "inflight" or info.get("chain_id") != chain_id:
            raise PermissionError(f"chain_id={chain_id!r} does not own chunk_id={chunk_id!r}")

        now = time.time()
        pipe = self._r.pipeline(transaction=True)
        pipe.srem(_inflight_key(job_id), chunk_id)
        pipe.sadd(_failed_key(job_id), chunk_id)
        pipe.hset(
            _chunk_key(job_id, chunk_id),
            mapping={
                "status": "failed",
                "completed_at": now,
                "lease_until": 0,
                "reason_code": reason_code,
            },
        )
        pipe.execute()
        return self.get_progress(job_id)

    def get_progress(self, job_id: str) -> ChunkProgress:
        meta = self._r.hgetall(_meta_key(job_id))
        total = int(meta.get("total_chunks", 0)) if meta else 0
        pending = self._r.llen(_pending_key(job_id))
        inflight = self._r.scard(_inflight_key(job_id))
        completed = self._r.scard(_completed_key(job_id))
        failed = self._r.scard(_failed_key(job_id))
        return ChunkProgress(
            total=total,
            pending=pending,
            inflight=inflight,
            completed=completed,
            failed=failed,
            all_done=(completed + failed) >= total and total > 0,
        )


def _lease_from_hash(info: dict[str, str]) -> ChunkLease:
    return ChunkLease(
        chunk_id=info["chunk_id"],
        job_id=info["job_id"],
        chain_id=info["chain_id"],
        payload_ref=PayloadRef.model_validate(json.loads(info["payload_ref"])),
        output_ref=OutputRef.model_validate(json.loads(info["output_ref"])),
        lease_until=float(info["lease_until"]),
        retry_count=int(info.get("retry_count", 0)),
        num_records=int(info.get("num_records", 0)),
    )
