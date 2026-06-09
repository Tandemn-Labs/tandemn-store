"""KoiTick model — one periodic Koi scheduler pass."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.ids import new_koi_tick_id
from tandemn_system_data.models._base import CanonicalModel, utc_now


class KoiTick(CanonicalModel):
    tick_id: str = Field(default_factory=new_koi_tick_id)
    user_id: str
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    status: str = "started"
    waiting_job_count: int = 0
    running_job_count: int = 0
    metadata_json: dict[str, Any] = Field(default_factory=dict)
