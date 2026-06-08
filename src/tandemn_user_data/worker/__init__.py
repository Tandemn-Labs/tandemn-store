"""Worker-side entry points.

Workers use WorkerClient for payload I/O and OrcaChunkClient for chunk
queue operations through Orca. Workers do not talk to Redis directly.
"""

from __future__ import annotations

from tandemn_user_data.worker.client import (
    WorkerClient,
    default_registry,
    fetch_payload,
    write_outputs,
)
from tandemn_user_data.worker.orca_chunk_client import OrcaChunkClient

__all__ = [
    "OrcaChunkClient",
    "WorkerClient",
    "default_registry",
    "fetch_payload",
    "write_outputs",
]
