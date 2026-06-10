"""Orca-side source indexer — DATA_ARCHITECTURE.md §7.

Orca passes a job's `input_source` JSONB blob and gets PayloadRefs ready
to enqueue. Persisting anything from the output is Orca's job; this
module must not import tandemn_system_data.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from tandemn_user_data.core import ConnectorRegistry, CredentialResolver, PayloadRef


def index_source(
    input_source: dict[str, Any],
    *,
    registry: ConnectorRegistry,
    resolver: CredentialResolver | None = None,
) -> Iterator[PayloadRef]:
    """Walk an input source and yield one PayloadRef per chunk.

    `input_source` must contain a `type` key matching a registered
    InputConnector; remaining keys (uri, format, chunk_size_lines, ...)
    are connector-specific.
    """
    if "type" not in input_source:
        raise ValueError("input_source must include a 'type' key matching a registered connector")

    connector = registry.input_for(input_source["type"])
    creds = None
    if resolver is not None:
        creds = resolver.resolve(input_source.get("credentials_ref"))

    yield from connector.index(input_source, creds=creds)
