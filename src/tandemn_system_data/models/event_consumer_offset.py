"""Event consumer cursor model — DATA_ARCHITECTURE.md §8.

Each consumer keeps one cursor into the Postgres events table and updates
it only after successful processing.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from tandemn_system_data.models._base import CanonicalModel, utc_now


class EventConsumerOffset(CanonicalModel):
    consumer_name: str
    last_event_id: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)
