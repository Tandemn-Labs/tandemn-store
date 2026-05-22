"""Chain model — DATA_ARCHITECTURE.md §5.

A chain is one launched serving unit tagged with:
  - alternative_id: which placement_alternative owns it
  - role: prefill | decode | aggregate (§5)
  - shape_json: copied from the alternative's sizing at launch
  - parallelism_json: e.g. {"tp": 2, "pp": 4}

Per §5 notes, prefill and decode chains in the same alternative MAY have
different hardware. The schema does not couple them.
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
    alternative_id: str
    role: ChainRole
    shape_json: dict[str, Any] = Field(default_factory=dict)
    parallelism_json: dict[str, Any] = Field(default_factory=dict)
    target_node: str | None = None
    status: ChainStatus = ChainStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
