"""Redis Streams client for the live event bus.

Phase 1a: connectivity only. Stream / consumer-group helpers land in
Phase 1b alongside the Event envelope.
"""

from __future__ import annotations

import os

import redis

DEFAULT_URL = "redis://localhost:56379/0"


class RedisStreamClient:
    """Owns a redis.Redis connection. One per process."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("TANDEMN_REDIS_URL", DEFAULT_URL)
        self._client = redis.from_url(self.url, decode_responses=True)

    @property
    def client(self) -> redis.Redis:
        return self._client

    def ping(self) -> bool:
        return bool(self._client.ping())
