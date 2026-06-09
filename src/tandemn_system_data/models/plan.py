"""Plan model — DATA_ARCHITECTURE.md §5.

Koi's multi-job scheduler plan for a Koi tick. A plan contains Koi's
rationale, the executable rank structure, and aggregate throughput target.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.ids import new_plan_id
from tandemn_system_data.models._base import CanonicalModel, utc_now


class Plan(CanonicalModel):
    plan_id: str = Field(default_factory=new_plan_id)
    tick_id: str
    koi_version: str | None = None
    rationale_json: dict[str, Any] = Field(default_factory=dict)
    plan_json: dict[str, Any] = Field(default_factory=dict)
    slo_json: dict[str, Any] = Field(default_factory=dict)
    required_throughput_tps: float | None = None
    status: str = "created"
    created_at: datetime = Field(default_factory=utc_now)
