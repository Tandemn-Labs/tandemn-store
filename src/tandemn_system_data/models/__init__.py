"""Pydantic models for the canonical entities in DATA_ARCHITECTURE.md §5.

Re-exports every entity model and shared enum at the package level so
consumers can write `from tandemn_system_data.models import Job, Chain, ...`.
"""

from __future__ import annotations

from tandemn_system_data.models._base import CanonicalModel, utc_now
from tandemn_system_data.models.chain import Chain
from tandemn_system_data.models.credentials import Credentials
from tandemn_system_data.models.enums import (
    ActionType,
    ChainRole,
    ChainStatus,
    JobKind,
    JobStatus,
    ReasonCode,
)
from tandemn_system_data.models.event import Event
from tandemn_system_data.models.event_consumer_offset import EventConsumerOffset
from tandemn_system_data.models.job import ChainAllocation, Job, RunningJob
from tandemn_system_data.models.plan import Plan, PlanAction
from tandemn_system_data.models.resource_map import ResourceMap, ResourcePool
from tandemn_system_data.models.user import User

__all__ = [
    "ActionType",
    "CanonicalModel",
    "Chain",
    "ChainAllocation",
    "ChainRole",
    "ChainStatus",
    "Credentials",
    "Event",
    "EventConsumerOffset",
    "Job",
    "JobKind",
    "JobStatus",
    "Plan",
    "PlanAction",
    "ReasonCode",
    "ResourceMap",
    "ResourcePool",
    "RunningJob",
    "User",
    "utc_now",
]
