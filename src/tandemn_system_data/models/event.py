"""Event row model — DATA_ARCHITECTURE.md §5 (events table) and §9 (catalog).

The durable side of the event bus: every event Redis Streams delivers
is also persisted here as an append-only audit log. The full typed
payload registry lives in tandemn_system_data.events.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.ids import new_event_id
from tandemn_system_data.models._base import CanonicalModel, utc_now


class Event(CanonicalModel):
    event_id: str = Field(default_factory=new_event_id)
    tenant_id: str | None = None
    job_id: str | None = None
    chain_id: str | None = None
    type: str
    payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
