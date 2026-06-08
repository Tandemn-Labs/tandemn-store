"""Orca/admin-side Redis chunk queue operations.

This is the control-plane Redis queue client. Orca uses it for all chunk
queue operations, including worker-proxied pull/renew/complete/fail
requests. Workers call Orca over HTTP; workers do not talk to Redis.
"""

from __future__ import annotations

import json
import os
import time

import redis

from tandemn_user_data.core import ChunkLease, ChunkProgress, OutputRef, PayloadRef, QueuedChunk

DEFAULT_REDIS_URL = "redis://localhost:56379/0"
DEFAULT_MAX_RETRIES = 3
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


def _output_order_key(job_id: str) -> str:
    return f"{_PREFIX}:{job_id}:output_order"


_RECLAIM_LUA = """
local inflight_key = KEYS[1]
local pending_key = KEYS[2]
local failed_key = KEYS[3]
local job_prefix = ARGV[1]
local now = tonumber(ARGV[2])

local members = redis.call('SMEMBERS', inflight_key)
local reclaimed = 0
local failed = 0

for _, cid in ipairs(members) do
  local chunk_key = job_prefix .. ':chunk:' .. cid
  local lease_until = tonumber(redis.call('HGET', chunk_key, 'lease_until')) or 0
  if lease_until > 0 and lease_until < now then
    local retry_count = (tonumber(redis.call('HGET', chunk_key, 'retry_count')) or 0) + 1
    local max_retries = tonumber(redis.call('HGET', chunk_key, 'max_retries')) or 3
    redis.call('SREM', inflight_key, cid)
    if retry_count >= max_retries then
      redis.call('SADD', failed_key, cid)
      redis.call('HSET', chunk_key,
        'status', 'failed',
        'retry_count', tostring(retry_count),
        'lease_until', '0',
        'reason_code', 'LEASE_EXPIRED')
      failed = failed + 1
    else
      redis.call('RPUSH', pending_key, cid)
      redis.call('HSET', chunk_key,
        'status', 'pending',
        'chain_id', '',
        'retry_count', tostring(retry_count),
        'lease_until', '0')
      reclaimed = reclaimed + 1
    end
  end
end

return {reclaimed, failed}
"""


_FORCE_RECLAIM_LUA = """
local inflight_key = KEYS[1]
local pending_key = KEYS[2]
local failed_key = KEYS[3]
local job_prefix = ARGV[1]

local targets = {}
for i = 2, #ARGV do targets[ARGV[i]] = true end

local members = redis.call('SMEMBERS', inflight_key)
local reclaimed = 0

for _, cid in ipairs(members) do
  local chunk_key = job_prefix .. ':chunk:' .. cid
  local owner = redis.call('HGET', chunk_key, 'chain_id') or ''
  if targets[owner] then
    redis.call('SREM', inflight_key, cid)
    redis.call('RPUSH', pending_key, cid)
    redis.call('HSET', chunk_key,
      'status', 'pending',
      'chain_id', '',
      'lease_until', '0')
    reclaimed = reclaimed + 1
  end
end

return reclaimed
"""


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


class RedisChunkQueueAdmin:
    """Orca/admin-side Redis chunk queue client."""

    def __init__(
        self, redis_url: str | None = None, *, lease_ttl_sec: int = DEFAULT_LEASE_TTL_SEC
    ) -> None:
        self.url = redis_url or os.getenv("TANDEMN_REDIS_URL", DEFAULT_REDIS_URL)
        self.lease_ttl_sec = lease_ttl_sec
        self._r = redis.from_url(self.url, decode_responses=True)
        self._reclaim_script = self._r.register_script(_RECLAIM_LUA)
        self._force_reclaim_script = self._r.register_script(_FORCE_RECLAIM_LUA)
        self._renew_script = self._r.register_script(_RENEW_LUA)

    def create_job_queue(
        self,
        job_id: str,
        chunks: list[QueuedChunk],
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        now = time.time()
        pipe = self._r.pipeline(transaction=True)
        pipe.hset(
            _meta_key(job_id),
            mapping={"job_id": job_id, "total_chunks": len(chunks), "created_at": now},
        )
        for chunk in chunks:
            pipe.hset(
                _chunk_key(job_id, chunk.chunk_id),
                mapping={
                    "chunk_id": chunk.chunk_id,
                    "job_id": job_id,
                    "payload_ref": chunk.payload_ref.model_dump_json(),
                    "output_ref": chunk.output_ref.model_dump_json(),
                    "num_records": chunk.num_records,
                    "metadata": json.dumps(chunk.metadata, separators=(",", ":")),
                    "status": "pending",
                    "chain_id": "",
                    "lease_until": 0,
                    "retry_count": 0,
                    "max_retries": max_retries,
                    "started_at": 0,
                    "completed_at": 0,
                    "reason_code": "",
                },
            )
            pipe.rpush(_pending_key(job_id), chunk.chunk_id)
            pipe.rpush(_output_order_key(job_id), chunk.chunk_id)
        pipe.execute()

    def pull_chunk(self, job_id: str, chain_id: str) -> ChunkLease | None:
        """Claim the next pending chunk for a chain.

        Intended to be called by Orca's `/chunks/next` endpoint, not by
        workers directly.
        """
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
        return _lease_from_hash(result[-1])

    def renew_lease(self, job_id: str, chunk_id: str, chain_id: str) -> bool:
        new_lease = time.time() + self.lease_ttl_sec
        renewed, _ = self._renew_script(
            keys=[_chunk_key(job_id, chunk_id)],
            args=[chain_id, new_lease],
        )
        return bool(int(renewed))

    def complete_chunk(self, job_id: str, chunk_id: str, chain_id: str) -> ChunkProgress:
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

    def reclaim_expired(self, job_id: str) -> dict[str, int]:
        reclaimed, failed = self._reclaim_script(
            keys=[_inflight_key(job_id), _pending_key(job_id), _failed_key(job_id)],
            args=[f"{_PREFIX}:{job_id}", time.time()],
        )
        return {"reclaimed": int(reclaimed), "failed": int(failed)}

    def force_reclaim(self, job_id: str, chain_ids: list[str]) -> int:
        if not chain_ids:
            return 0
        return int(
            self._force_reclaim_script(
                keys=[_inflight_key(job_id), _pending_key(job_id), _failed_key(job_id)],
                args=[f"{_PREFIX}:{job_id}", *chain_ids],
            )
        )

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

    def get_output_order(self, job_id: str) -> list[str]:
        return self._r.lrange(_output_order_key(job_id), 0, -1)

    def cleanup_job(self, job_id: str) -> None:
        chunk_ids = self.get_output_order(job_id)
        pipe = self._r.pipeline(transaction=True)
        for key in (
            _meta_key(job_id),
            _pending_key(job_id),
            _inflight_key(job_id),
            _completed_key(job_id),
            _failed_key(job_id),
            _output_order_key(job_id),
        ):
            pipe.delete(key)
        for chunk_id in chunk_ids:
            pipe.delete(_chunk_key(job_id, chunk_id))
        pipe.execute()


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
