"""Job model — DATA_ARCHITECTURE.md §5.

A job carries:
  - `spec_json`: the user-supplied job specification.
  - `input_source` / `output_target`: where the data lives, NEVER the data itself.
    These are JSONB so the connector framework can describe any source
    without schema changes.

Lifecycle: waiting -> running <-> paused -> finished. New jobs start
WAITING until a plan action places them. finish_reason is NULL on
success, a reason code (FAILED, CANCELLED, ...) otherwise.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.ids import new_job_id
from tandemn_system_data.models._base import CanonicalModel, utc_now
from tandemn_system_data.models.enums import ChainRole, ChainStatus, JobKind, JobStatus


class Job(CanonicalModel):
    job_id: str = Field(default_factory=new_job_id)
    user_id: str
    kind: JobKind
    spec_json: dict[str, Any] = Field(default_factory=dict)
    input_source: dict[str, Any] = Field(default_factory=dict)
    output_target: dict[str, Any] = Field(default_factory=dict)
    status: JobStatus = JobStatus.WAITING
    finish_reason: str | None = None  # NULL = success (when finished)
    created_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None


class ChainAllocation(CanonicalModel):
    """Read-model: one chain currently holding resources for a job.
    Derived from the chains table, never stored separately."""

    chain_id: str
    plan_id: str | None
    role: ChainRole
    status: ChainStatus
    shape_json: dict[str, Any] = Field(default_factory=dict)
    target_node: str | None = None


class RunningJob(CanonicalModel):
    """Read-model for the Koi tick: a running job plus the chains
    serving it."""

    job: Job
    chains: list[ChainAllocation] = Field(default_factory=list)
