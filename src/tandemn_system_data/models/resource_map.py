"""ResourceMap — the shared wire contract for Orca's live resource view.

One Postgres row per ``user_id`` in ``resource_maps`` (``pools_json`` +
monotonic ``version``). Orca's reconciler is the single writer; Koi reads
via ``ResourceMapStore.get``. Not refreshed by polling cloud providers —
reflects capacity the user already holds, updated when jobs reserve or
release resources (place / preempt / swap / finish).

Shape example:

    {
      "version": 41,
      "updated_at": "2026-06-10T12:00:00Z",
      "pools": {
        "aws": {"g6e.12xlarge": {"total": 8, "available": 3}},
        "gcp": {"a3-highgpu-8g": {"total": 2, "available": 2}}
      }
    }
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.models._base import CanonicalModel, utc_now


class ResourcePool(CanonicalModel):
    """Reserved capacity for one instance type with one provider."""

    total: int
    available: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourceMap(CanonicalModel):
    version: int = 0
    updated_at: datetime = Field(default_factory=utc_now)
    # provider -> instance_type -> pool, e.g. pools["aws"]["g6e.12xlarge"]
    pools: dict[str, dict[str, ResourcePool]] = Field(default_factory=dict)
