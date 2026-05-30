"""Postgres-backed event log and consumer cursors.

DATA_ARCHITECTURE.md §8 uses Postgres as both the durable audit log and
the MVP delivery mechanism. Producers append to `events`; consumers read
after their own cursor in `event_consumer_offsets` and advance the cursor
only after successful processing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from tandemn_system_data.clients.postgres import PostgresClient
from tandemn_system_data.db import EventConsumerOffsetRow, EventRow
from tandemn_system_data.models import Event


class PostgresEventLog:
    """Append/read/ack wrapper around the Postgres events table."""

    def __init__(self, pg: PostgresClient) -> None:
        self._pg = pg

    def append(self, event: Event) -> str:
        """Persist an event row and return event_id."""
        with self._pg.begin() as s:
            s.add(
                EventRow(
                    event_id=event.event_id,
                    user_id=event.user_id,
                    job_id=event.job_id,
                    chain_id=event.chain_id,
                    type=event.type,
                    payload_json=event.payload_json,
                    created_at=event.created_at,
                )
            )
        return event.event_id

    def read_after(
        self,
        last_event_id: str | None,
        *,
        limit: int = 100,
        types: set[str] | None = None,
    ) -> list[Event]:
        """Read events after a cursor, ordered by (created_at, event_id).

        ULID event IDs are time-sortable, but ordering by timestamp first
        keeps the query intuitive for operators. `last_event_id=None`
        starts at the beginning.
        """
        with self._pg.session() as s:
            stmt = select(EventRow).order_by(EventRow.created_at, EventRow.event_id).limit(limit)
            if last_event_id is not None:
                last = s.get(EventRow, last_event_id)
                if last is not None:
                    stmt = stmt.where(
                        (EventRow.created_at > last.created_at)
                        | (
                            (EventRow.created_at == last.created_at)
                            & (EventRow.event_id > last.event_id)
                        )
                    )
                else:
                    stmt = stmt.where(EventRow.event_id > last_event_id)
            if types:
                stmt = stmt.where(EventRow.type.in_(types))
            rows = list(s.execute(stmt).scalars())
            return [self._row_to_event(r) for r in rows]

    def get_cursor(self, consumer_name: str) -> str | None:
        with self._pg.session() as s:
            row = s.get(EventConsumerOffsetRow, consumer_name)
            return None if row is None else row.last_event_id

    def read_for_consumer(
        self,
        consumer_name: str,
        *,
        limit: int = 100,
        types: set[str] | None = None,
    ) -> list[Event]:
        return self.read_after(self.get_cursor(consumer_name), limit=limit, types=types)

    def ack(self, consumer_name: str, event_id: str) -> None:
        """Advance a consumer cursor after successful processing."""
        now = datetime.now(UTC)
        with self._pg.begin() as s:
            row = s.get(EventConsumerOffsetRow, consumer_name)
            if row is None:
                s.add(
                    EventConsumerOffsetRow(
                        consumer_name=consumer_name,
                        last_event_id=event_id,
                        updated_at=now,
                    )
                )
            else:
                row.last_event_id = event_id
                row.updated_at = now

    @staticmethod
    def _row_to_event(row: EventRow) -> Event:
        return Event(
            event_id=row.event_id,
            user_id=row.user_id,
            job_id=row.job_id,
            chain_id=row.chain_id,
            type=row.type,
            payload_json=row.payload_json,
            created_at=row.created_at,
        )


def event_payload(event: Event) -> dict[str, Any]:
    """Small helper for consumers that only need payload_json."""
    return event.payload_json
