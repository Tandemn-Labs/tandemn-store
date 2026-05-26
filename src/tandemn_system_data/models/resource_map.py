"""ResourceMap model — DATA_ARCHITECTURE.md §5.

A snapshot of available GPUs/nodes for a user. snapshot_json is
intentionally schemaless so the inventory model can evolve without a
migration; the database indexes it with GIN.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.ids import new_resource_map_id
from tandemn_system_data.models._base import CanonicalModel, utc_now


class ResourceMap(CanonicalModel):
    resource_map_id: str = Field(default_factory=new_resource_map_id)
    user_id: str
    snapshot_json: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime = Field(default_factory=utc_now)
