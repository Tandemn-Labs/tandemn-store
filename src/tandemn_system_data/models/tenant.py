"""Tenant model — DATA_ARCHITECTURE.md §5."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from tandemn_system_data.ids import new_tenant_id
from tandemn_system_data.models._base import CanonicalModel, utc_now


class Tenant(CanonicalModel):
    tenant_id: str = Field(default_factory=new_tenant_id)
    name: str
    created_at: datetime = Field(default_factory=utc_now)
