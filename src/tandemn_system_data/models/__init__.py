"""Pydantic models for the canonical entities in DATA_ARCHITECTURE.md §5.

Re-exports every entity model and shared enum at the package level so
consumers can write `from tandemn_system_data.models import Job, Chain, ...`.
"""

from __future__ import annotations

from tandemn_system_data.models._base import CanonicalModel, utc_now
from tandemn_system_data.models.attempt import Attempt
from tandemn_system_data.models.chain import Chain
from tandemn_system_data.models.credentials import Credentials
from tandemn_system_data.models.enums import (
    AlternativeStatus,
    AttemptStatus,
    ChainRole,
    ChainStatus,
    JobKind,
    JobStatus,
    OutcomeStatus,
    PlacementStrategy,
    ReasonCode,
)
from tandemn_system_data.models.event import Event
from tandemn_system_data.models.job import Job
from tandemn_system_data.models.outcome import Outcome
from tandemn_system_data.models.placement_alternative import PlacementAlternative
from tandemn_system_data.models.plan import Plan
from tandemn_system_data.models.resource_map import ResourceMap
from tandemn_system_data.models.user import User

__all__ = [
    # Base
    "CanonicalModel",
    "utc_now",
    # Entities
    "Attempt",
    "Chain",
    "Credentials",
    "Plan",
    "Event",
    "Job",
    "Outcome",
    "PlacementAlternative",
    "ResourceMap",
    "User",
    # Enums
    "AlternativeStatus",
    "AttemptStatus",
    "ChainRole",
    "ChainStatus",
    "JobKind",
    "JobStatus",
    "OutcomeStatus",
    "PlacementStrategy",
    "ReasonCode",
]
