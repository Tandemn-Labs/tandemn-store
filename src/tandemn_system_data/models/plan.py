"""Plan model — DATA_ARCHITECTURE.md §5.

Koi's placement plan for a job. A plan contains both Koi's rationale and
the executable placement plan (alternatives + SLO).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.ids import new_plan_id
from tandemn_system_data.models._base import CanonicalModel, utc_now


class Plan(CanonicalModel):
    plan_id: str = Field(default_factory=new_plan_id)
    job_id: str
    koi_version: str | None = None
    rationale_json: dict[str, Any] = Field(default_factory=dict)
    plan_json: dict[str, Any] = Field(default_factory=dict)
    slo_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
