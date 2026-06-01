"""Chunk metadata types shared by Orca and workers.

Chunks carry pointers and execution metadata, not prompt bytes. Workers
can import this module because it lives in tandemn_user_data and depends
only on PayloadRef / OutputRef.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from tandemn_user_data.core.record import OutputRef, PayloadRef, _UserDataModel


class ChunkStatus(StrEnum):
    PENDING = "pending"
    INFLIGHT = "inflight"
    COMPLETED = "completed"
    FAILED = "failed"


class ChunkRef(_UserDataModel):
    chunk_id: str
    job_id: str
    payload_ref: PayloadRef
    output_ref: OutputRef
    num_records: int = 0


class ChunkLease(_UserDataModel):
    chunk_id: str
    job_id: str
    chain_id: str
    payload_ref: PayloadRef
    output_ref: OutputRef
    lease_until: float
    retry_count: int = 0
    num_records: int = 0


class ChunkProgress(_UserDataModel):
    total: int
    pending: int
    inflight: int
    completed: int
    failed: int
    all_done: bool


class ChunkState(_UserDataModel):
    chunk_id: str
    job_id: str
    payload_ref: PayloadRef
    output_ref: OutputRef
    status: ChunkStatus = ChunkStatus.PENDING
    chain_id: str | None = None
    lease_until: float = 0
    retry_count: int = 0
    num_records: int = 0
    started_at: float = 0
    completed_at: float = 0
    reason_code: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class QueuedChunk(_UserDataModel):
    """Input shape for creating a job queue."""

    chunk_id: str
    payload_ref: PayloadRef
    output_ref: OutputRef
    num_records: int = 0
    metadata: dict[str, str] = Field(default_factory=dict)


class ChunkQueueMeta(_UserDataModel):
    job_id: str
    total_chunks: int
    created_at: datetime
