"""Worker-side entry points: fetch_payload, write_outputs, WorkerClient."""

from __future__ import annotations

from tandemn_user_data.worker.client import (
    WorkerClient,
    default_registry,
    fetch_payload,
    write_outputs,
)
from tandemn_user_data.worker.redis_chunk_queue import RedisChunkQueueWorker

__all__ = [
    "RedisChunkQueueWorker",
    "WorkerClient",
    "default_registry",
    "fetch_payload",
    "write_outputs",
]
