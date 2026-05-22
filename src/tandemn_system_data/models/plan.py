"""Plan model — DATA_ARCHITECTURE.md §5 and §6.

A plan carries the structured placement (ordered alternatives) plus
the SLO target. The actual `placement_alternatives` rows reference
back via `plan_id`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.ids import new_plan_id
from tandemn_system_data.models._base import CanonicalModel, utc_now


class Plan(CanonicalModel):
    plan_id: str = Field(default_factory=new_plan_id)
    plan_json: dict[str, Any] = Field(default_factory=dict)
    slo_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
