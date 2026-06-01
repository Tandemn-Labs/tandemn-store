"""Orca/admin-side Redis chunk queue operations.

This is the control-plane half of the chunk queue. Orca uses it to create
job queues, inspect progress, reclaim expired chunks, force reclaim dead
chains, and clean up.

Workers use tandemn_user_data.worker.RedisChunkQueueWorker for pull /
renew / complete / fail.
"""

from __future__ import annotations

import json
import os
import time

import redis

from tandemn_user_data.core import ChunkProgress, QueuedChunk

DEFAULT_REDIS_URL = "redis://localhost:56379/0"
DEFAULT_MAX_RETRIES = 3
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


class RedisChunkQueueAdmin:
    """Orca/admin-side Redis chunk queue client."""

    def __init__(self, redis_url: str | None = None) -> None:
        self.url = redis_url or os.getenv("TANDEMN_REDIS_URL", DEFAULT_REDIS_URL)
        self._r = redis.from_url(self.url, decode_responses=True)
        self._reclaim_script = self._r.register_script(_RECLAIM_LUA)
        self._force_reclaim_script = self._r.register_script(_FORCE_RECLAIM_LUA)

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
