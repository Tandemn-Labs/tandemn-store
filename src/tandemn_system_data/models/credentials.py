"""Credentials model — DATA_ARCHITECTURE.md §5 and §7.

Short-lived, scoped credentials minted by Orca's CredentialIssuer.
Workers resolve a `credentials_ref` to a usable token via Orca's
narrow GET /credentials/<ref> endpoint; workers NEVER read this table
directly. `secret_payload` is encrypted at rest in production.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.ids import new_credentials_ref
from tandemn_system_data.models._base import CanonicalModel, utc_now


class Credentials(CanonicalModel):
    credentials_ref: str = Field(default_factory=new_credentials_ref)
    tenant_id: str
    scope_json: dict[str, Any] = Field(default_factory=dict)
    secret_payload: bytes
    expires_at: datetime
    rotated_from: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
