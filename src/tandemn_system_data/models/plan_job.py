"""PlanJob model — join row between a scheduler plan and admitted jobs."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from tandemn_system_data.models._base import CanonicalModel, utc_now


class PlanJob(CanonicalModel):
    plan_id: str
    job_id: str
    priority: int = 0
    required_throughput_tps: float | None = None
    status: str = "admitted"
    admitted_at: datetime = Field(default_factory=utc_now)
