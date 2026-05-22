"""Outcome model — DATA_ARCHITECTURE.md §5.

A per-chain outcome with metrics (latency, realized_tps, ttft, etc.).
Outcomes feed Koi's learning loop.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.ids import new_outcome_id
from tandemn_system_data.models._base import CanonicalModel, utc_now
from tandemn_system_data.models.enums import OutcomeStatus


class Outcome(CanonicalModel):
    outcome_id: str = Field(default_factory=new_outcome_id)
    chain_id: str
    status: OutcomeStatus
    reason_code: str | None = None
    metrics_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
