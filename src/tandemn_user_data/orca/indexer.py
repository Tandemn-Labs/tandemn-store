"""Orca-side source indexer — DATA_ARCHITECTURE.md §7.

Thin wrapper: Orca passes the job's `input_source` blob (the JSONB
column from the jobs table) and gets back a list of PayloadRefs ready
to be enqueued in Redis.

This module deliberately does NOT import tandemn_system_data — the
indexer is a tandemn_user_data utility. Orca is responsible for
persisting whatever it needs from the indexer's output.
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
    """Walk an input source and yield PayloadRefs.

    Args:
        input_source: The JSONB blob from jobs.input_source. Must contain
                      at least a `type` key matching a registered
                      InputConnector. Connector-specific keys
                      (uri, format, chunk_size_lines, ...) are
                      interpreted by that connector's `index()` method.
        registry:     ConnectorRegistry containing the connectors Orca
                      supports.
        resolver:     Optional CredentialResolver. If `input_source`
                      contains `credentials_ref` and a resolver is given,
                      the resolver is called once and the resolved value
                      is passed to the connector's index() call.

    Yields:
        PayloadRef instances, one per chunk produced by the connector.

    Raises:
        KeyError: if `input_source["type"]` is not registered.
        ValueError: if `input_source` is missing required keys.
    """
    if "type" not in input_source:
        raise ValueError("input_source must include a 'type' key matching a registered connector")

    connector = registry.input_for(input_source["type"])
    creds = None
    if resolver is not None:
        creds = resolver.resolve(input_source.get("credentials_ref"))

    yield from connector.index(input_source, creds=creds)


def index_source_to_list(
    input_source: dict[str, Any],
    *,
    registry: ConnectorRegistry,
    resolver: CredentialResolver | None = None,
) -> list[PayloadRef]:
    """Eager variant of index_source(); convenient for callers that
    want a list to count and enqueue."""
    return list(index_source(input_source, registry=registry, resolver=resolver))
