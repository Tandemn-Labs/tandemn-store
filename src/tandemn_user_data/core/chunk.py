"""Chunk metadata types shared by Orca and workers.

Chunks carry pointers and execution metadata, not prompt bytes. Workers
can import this module because it lives in tandemn_user_data and depends
only on PayloadRef / OutputRef.
"""

from __future__ import annotations

from pydantic import Field

from tandemn_user_data.core.record import OutputRef, PayloadRef, _UserDataModel


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


class QueuedChunk(_UserDataModel):
    """Input shape for creating a job queue."""

    chunk_id: str
    payload_ref: PayloadRef
    output_ref: OutputRef
    num_records: int = 0
    metadata: dict[str, str] = Field(default_factory=dict)
