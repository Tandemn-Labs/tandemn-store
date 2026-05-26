"""Job model — DATA_ARCHITECTURE.md §5.

A job carries:
  - `spec_json`: the user-supplied job specification.
  - `input_source` / `output_target`: where the data lives, NEVER the data itself.
    These are JSONB so the connector framework can describe any source
    (S3, Snowflake, BigQuery, local, ...) without schema changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.ids import new_job_id
from tandemn_system_data.models._base import CanonicalModel, utc_now
from tandemn_system_data.models.enums import JobKind, JobStatus


class Job(CanonicalModel):
    job_id: str = Field(default_factory=new_job_id)
    user_id: str
    kind: JobKind
    spec_json: dict[str, Any] = Field(default_factory=dict)
    input_source: dict[str, Any] = Field(default_factory=dict)
    output_target: dict[str, Any] = Field(default_factory=dict)
    status: JobStatus = JobStatus.SUBMITTED
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
