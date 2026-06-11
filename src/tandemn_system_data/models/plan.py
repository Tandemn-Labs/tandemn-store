"""Plan model — one cluster-wide scheduling decision from a Koi pass.

A plan is a rationale plus a list of per-job actions. The action type
determines the job status change Orca applies:

    place    waiting -> running   launch the ladder (gang: all chains at once)
    keep     running              no change
    defer    waiting              no change
    preempt  running -> paused    tear down the job's chains
    swap     running              relaunch on new_ladder

Ladders (ordered rank configs with expected TPS) live INSIDE the action
JSON — there is no ranks table and no traversal in the MVP. Orca
launches the chains a placement describes in one shot (gang scheduling
for PD: e.g. 2 prefill 8xH100 + 1 decode 8xA100 together).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.ids import new_plan_id
from tandemn_system_data.models._base import CanonicalModel, utc_now
from tandemn_system_data.models.enums import ActionType


class PlanAction(CanonicalModel):
    """One per-job action inside a plan.

    ladder entries are schemaless dicts (shape, parallelism,
    expected_tps, ...) — their structure is Koi's contract with Orca,
    not the database's.
    """

    job_id: str
    type: ActionType
    ladder: list[dict[str, Any]] | None = None  # place / swap
    target_tps: float | None = None


class Plan(CanonicalModel):
    plan_id: str = Field(default_factory=new_plan_id)
    user_id: str
    koi_version: str | None = None
    tick_rationale: str = ""
    actions: list[PlanAction] = Field(default_factory=list)
    status: str = "created"  # created -> applied
    created_at: datetime = Field(default_factory=utc_now)
