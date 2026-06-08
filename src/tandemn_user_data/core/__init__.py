"""Core types for tandemn_user_data — DATA_ARCHITECTURE.md §7.

Re-exports:
  - PayloadRef, OutputRef, NormalizedRecord
  - InputConnector, OutputConnector, ConnectorRegistry (protocols)
  - CredentialResolver protocol + HttpCredentialResolver / NullResolver
"""

from __future__ import annotations

from tandemn_user_data.core.base import (
    ConnectorRegistry,
    CredentialResolver,
    InputConnector,
    OutputConnector,
)
from tandemn_user_data.core.chunk import (
    ChunkLease,
    ChunkProgress,
    QueuedChunk,
)
from tandemn_user_data.core.credentials_client import (
    HttpCredentialResolver,
    NullResolver,
)
from tandemn_user_data.core.record import (
    NormalizedRecord,
    OutputRef,
    PayloadRef,
)

__all__ = [
    "ConnectorRegistry",
    "CredentialResolver",
    "ChunkLease",
    "ChunkProgress",
    "HttpCredentialResolver",
    "InputConnector",
    "NormalizedRecord",
    "NullResolver",
    "OutputConnector",
    "OutputRef",
    "PayloadRef",
    "QueuedChunk",
]
