"""PlacementAlternative model — DATA_ARCHITECTURE.md §5 and §6.

Rules enforced here (from DATA_ARCHITECTURE.md):

- `strategy = 'pd_disaggregated'`  =>  `pd_ratio` MUST be > 0.
- `strategy = 'aggregate'`         =>  `pd_ratio` MUST be NULL.
  Prefill has no throughput; SLO arithmetic is decode-side only.

The `sizing_json` shape is asymmetric by role (see §5 notes):
  pd_disaggregated:
    { prefill: {shape}, decode: {shape, target_chains, est_tps_per_chain} }
  aggregate:
    { aggregate: {shape, target_chains, est_tps_per_chain} }

We do not validate `sizing_json` here beyond presence: the structure is
JSONB so Koi can evolve it. Strict shape validation belongs in Koi.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from tandemn_system_data.ids import new_placement_alternative_id
from tandemn_system_data.models._base import CanonicalModel, utc_now
from tandemn_system_data.models.enums import AlternativeStatus, PlacementStrategy


class PlacementAlternative(CanonicalModel):
    alternative_id: str = Field(default_factory=new_placement_alternative_id)
    plan_id: str
    rank: int = Field(ge=0, description="0 = first to try; higher = fallback order")
    strategy: PlacementStrategy
    pd_ratio: float | None = Field(
        default=None,
        gt=0,
        description="prefill_per_decode; required for pd_disaggregated, must be NULL for aggregate",
    )
    sizing_json: dict[str, Any] = Field(default_factory=dict)
    estimated_throughput_tps: float | None = Field(default=None, ge=0)
    status: AlternativeStatus = AlternativeStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _enforce_pd_ratio_rules(self) -> PlacementAlternative:
        if self.strategy is PlacementStrategy.PD_DISAGGREGATED:
            if self.pd_ratio is None:
                raise ValueError("pd_ratio is required when strategy='pd_disaggregated'")
        elif self.strategy is PlacementStrategy.AGGREGATE:
            if self.pd_ratio is not None:
                raise ValueError("pd_ratio must be NULL when strategy='aggregate'")
        return self
