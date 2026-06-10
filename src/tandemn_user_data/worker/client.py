"""Worker-side entry point — DATA_ARCHITECTURE.md §7.

Workers receive chunk metadata (payload_ref / output_ref dicts) and use
WorkerClient to move bytes. They never see source-specific URIs and never
hold long-lived credentials.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from tandemn_user_data.connectors import S3Connector
from tandemn_user_data.core import (
    ConnectorRegistry,
    CredentialResolver,
    NormalizedRecord,
    NullResolver,
    OutputRef,
    PayloadRef,
)


def default_registry() -> ConnectorRegistry:
    """Registry with the MVP connectors (s3)."""
    reg = ConnectorRegistry()
    reg.register(S3Connector())
    return reg


class WorkerClient:
    """Facade over the connector registry + credential resolver."""

    def __init__(
        self,
        registry: ConnectorRegistry | None = None,
        resolver: CredentialResolver | None = None,
    ) -> None:
        self._registry = registry or default_registry()
        self._resolver = resolver or NullResolver()

    def fetch_payload(
        self,
        payload_ref: PayloadRef | dict[str, Any],
    ) -> Iterator[NormalizedRecord]:
        """Resolve credentials, pick the InputConnector, stream records."""
        ref = (
            payload_ref
            if isinstance(payload_ref, PayloadRef)
            else PayloadRef.model_validate(payload_ref)
        )
        connector = self._registry.input_for(ref.type)
        creds = self._resolver.resolve(ref.credentials_ref)
        yield from connector.read(ref, creds=creds)

    def write_outputs(
        self,
        output_ref: OutputRef | dict[str, Any],
        records: Iterable[NormalizedRecord],
    ) -> int:
        """Resolve credentials, pick the OutputConnector, write records."""
        ref = (
            output_ref
            if isinstance(output_ref, OutputRef)
            else OutputRef.model_validate(output_ref)
        )
        connector = self._registry.output_for(ref.type)
        creds = self._resolver.resolve(ref.credentials_ref)
        return connector.write(ref, records, creds=creds)
