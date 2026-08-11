"""Canonical rank model: one job-scoped serving configuration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.ids import new_rank_id
from tandemn_system_data.models._base import CanonicalModel, utc_now
from tandemn_system_data.models.enums import RankRole, RankStatus


class Rank(CanonicalModel):
    rank_id: str = Field(default_factory=new_rank_id)
    job_id: str
    plan_id: str | None = None
    role: RankRole
    shape_json: dict[str, Any] = Field(default_factory=dict)
    n_replicas: int = Field(ge=1)
    status: RankStatus = RankStatus.LAUNCHING
    reason_code: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
