"""Redis Streams client for Tandemn's live event bus.

DATA_ARCHITECTURE.md §8 splits events into:

  - Postgres `events` table: durable CP audit record.
  - Redis Streams: AP live delivery path between Orca and Koi.

This client implements only the Redis side. Writers should persist the
Event row to Postgres first, then call `emit(event)` here. Consumers are
expected to be idempotent on `event_id`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

import redis

from tandemn_system_data.models import Event

DEFAULT_URL = "redis://localhost:56379/0"
GLOBAL_STREAM = "events.global"
USER_STREAM_PREFIX = "events.user."


class StreamMessage:
    """Parsed Redis Stream message.

    `message_id` is Redis's stream ID. `event` is the canonical event
    envelope stored in the message fields.
    """

    def __init__(self, message_id: str, event: Event) -> None:
        self.message_id = message_id
        self.event = event


class RedisStreamClient:
    """Owns a redis.Redis connection. One per process."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("TANDEMN_REDIS_URL", DEFAULT_URL)
        self._client = redis.from_url(self.url, decode_responses=True)
        self._r = self._client

    @property
    def client(self) -> redis.Redis:
        return self._client

    def ping(self) -> bool:
        return bool(self._client.ping())

    # ------------------------------------------------------------------
    # Stream names
    # ------------------------------------------------------------------

    @staticmethod
    def user_stream(user_id: str) -> str:
        if not user_id:
            raise ValueError("user_id is required")
        return f"{USER_STREAM_PREFIX}{user_id}"

    # ------------------------------------------------------------------
    # Emission
    # ------------------------------------------------------------------

    def emit(
        self,
        event: Event,
        *,
        stream: str = GLOBAL_STREAM,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        """XADD one event to a Redis stream and return the Redis message ID."""
        return self._r.xadd(
            stream,
            self._event_to_fields(event),
            maxlen=maxlen,
            approximate=approximate,
        )

    def emit_with_user_fanout(
        self,
        event: Event,
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> tuple[str, str | None]:
        """Emit to events.global and, if event.user_id exists, events.user.<id>.

        Returns (global_message_id, user_message_id | None).
        """
        global_id = self.emit(event, stream=GLOBAL_STREAM, maxlen=maxlen, approximate=approximate)
        user_id = None
        if event.user_id:
            user_id = self.emit(
                event,
                stream=self.user_stream(event.user_id),
                maxlen=maxlen,
                approximate=approximate,
            )
        return global_id, user_id

    # ------------------------------------------------------------------
    # Consumer groups
    # ------------------------------------------------------------------

    def create_group(self, stream: str, group: str, *, start_id: str = "0") -> None:
        """Create a consumer group. Idempotent if the group already exists."""
        try:
            self._r.xgroup_create(stream, group, id=start_id, mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        count: int = 10,
        block_ms: int = 0,
        last_id: str = ">",
    ) -> list[StreamMessage]:
        """Read messages for a consumer group.

        `last_id='>'` reads new messages. Use `last_id='0'` to inspect
        this consumer's pending messages.
        """
        raw = self._r.xreadgroup(
            group,
            consumer,
            {stream: last_id},
            count=count,
            block=block_ms,
        )
        return self._parse_xread(raw)

    def ack(self, stream: str, group: str, *message_ids: str) -> int:
        if not message_ids:
            return 0
        return int(self._r.xack(stream, group, *message_ids))

    def pending_summary(self, stream: str, group: str) -> dict[str, Any]:
        """Return Redis XPENDING summary for a group."""
        return self._r.xpending(stream, group)

    def pending_range(
        self,
        stream: str,
        group: str,
        *,
        min_id: str = "-",
        max_id: str = "+",
        count: int = 10,
        consumer: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return detailed pending entries."""
        return self._r.xpending_range(stream, group, min_id, max_id, count, consumername=consumer)

    def claim_stale(
        self,
        stream: str,
        group: str,
        consumer: str,
        message_ids: list[str],
        *,
        min_idle_ms: int,
    ) -> list[StreamMessage]:
        """Claim pending messages that have been idle for at least min_idle_ms."""
        if not message_ids:
            return []
        raw = self._r.xclaim(stream, group, consumer, min_idle_ms, message_ids)
        return [StreamMessage(mid, self._fields_to_event(fields)) for mid, fields in raw]

    # ------------------------------------------------------------------
    # Direct range reads (replay/debug)
    # ------------------------------------------------------------------

    def read_range(
        self, stream: str, *, start: str = "-", end: str = "+", count: int = 100
    ) -> list[StreamMessage]:
        raw = self._r.xrange(stream, min=start, max=end, count=count)
        return [StreamMessage(mid, self._fields_to_event(fields)) for mid, fields in raw]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _event_to_fields(event: Event) -> dict[str, str]:
        return {
            "event_id": event.event_id,
            "user_id": event.user_id or "",
            "job_id": event.job_id or "",
            "chain_id": event.chain_id or "",
            "type": event.type,
            "payload_json": json.dumps(event.payload_json, separators=(",", ":")),
            "created_at": event.created_at.isoformat(),
        }

    @staticmethod
    def _fields_to_event(fields: dict[str, str]) -> Event:
        return Event(
            event_id=fields["event_id"],
            user_id=fields.get("user_id") or None,
            job_id=fields.get("job_id") or None,
            chain_id=fields.get("chain_id") or None,
            type=fields["type"],
            payload_json=json.loads(fields.get("payload_json") or "{}"),
            created_at=datetime.fromisoformat(fields["created_at"]),
        )

    @classmethod
    def _parse_xread(
        cls, raw: list[tuple[str, list[tuple[str, dict[str, str]]]]]
    ) -> list[StreamMessage]:
        messages: list[StreamMessage] = []
        for _, entries in raw:
            for message_id, fields in entries:
                messages.append(StreamMessage(message_id, cls._fields_to_event(fields)))
        return messages
