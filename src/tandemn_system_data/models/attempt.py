"""Attempt model — DATA_ARCHITECTURE.md §5.

One row per launch attempt of a chain. `reason_code` is free-form text
(typically one of ReasonCode) so new codes can be added without a migration.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from tandemn_system_data.ids import new_attempt_id
from tandemn_system_data.models._base import CanonicalModel, utc_now
from tandemn_system_data.models.enums import AttemptStatus


class Attempt(CanonicalModel):
    attempt_id: str = Field(default_factory=new_attempt_id)
    chain_id: str
    status: AttemptStatus = AttemptStatus.STARTED
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: datetime | None = None
    reason_code: str | None = None
