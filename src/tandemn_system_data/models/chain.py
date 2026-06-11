"""Chain model — one launched serving unit.

Chains belong to a JOB (plan actions are per-job, so chains are not
shared). plan_id records which plan placed the chain — provenance only,
no FK, so plans and chains have independent lifecycles.

shape_json carries everything about the hardware and parallelism, e.g.
{"gpu": "H100", "count": 8, "tp": 2, "pp": 4}. Prefill and decode
chains of the same job may have different shapes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.ids import new_chain_id
from tandemn_system_data.models._base import CanonicalModel, utc_now
from tandemn_system_data.models.enums import ChainRole, ChainStatus


class Chain(CanonicalModel):
    chain_id: str = Field(default_factory=new_chain_id)
    job_id: str
    plan_id: str | None = None
    role: ChainRole
    shape_json: dict[str, Any] = Field(default_factory=dict)
    target_node: str | None = None
    status: ChainStatus = ChainStatus.LAUNCHING
    created_at: datetime = Field(default_factory=utc_now)
