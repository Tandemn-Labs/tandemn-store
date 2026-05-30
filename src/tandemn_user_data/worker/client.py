"""Worker-side entry points — DATA_ARCHITECTURE.md §7.

Workers pop chunk metadata from the chunk queue and call these two functions. They never
touch the connector registry directly, never see source-specific URIs,
and never hold long-lived credentials.

Usage in a worker loop:

    from tandemn_user_data.worker import WorkerClient, default_registry
    from tandemn_user_data.core import LocalCredentialsCache

    resolver = LocalCredentialsCache()             # or HTTP-backed in prod
    worker   = WorkerClient(default_registry(), resolver)

    while True:
        chunk = chunk_queue_pop()
        records = list(worker.fetch_payload(chunk["payload_ref"]))
        outputs = vllm.generate(records)
        worker.write_outputs(chunk["output_ref"], outputs)
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from tandemn_user_data.connectors import LocalFileConnector, S3Connector
from tandemn_user_data.core import (
    ConnectorRegistry,
    CredentialResolver,
    NormalizedRecord,
    NullResolver,
    OutputRef,
    PayloadRef,
)


def default_registry() -> ConnectorRegistry:
    """Return a registry pre-populated with the MVP reference connectors.

    Applications can build a custom registry instead and add their own
    connectors. This factory is the convenience path for the workers and
    the demo scripts.
    """
    reg = ConnectorRegistry()
    reg.register(LocalFileConnector())
    reg.register(S3Connector())
    return reg


class WorkerClient:
    """Worker-facing facade around the connector registry + resolver.

    The class is a thin holder; the two public methods do the work.
    """

    def __init__(
        self,
        registry: ConnectorRegistry | None = None,
        resolver: CredentialResolver | None = None,
    ) -> None:
        self._registry = registry or default_registry()
        self._resolver = resolver or NullResolver()

    # ----- input ----------------------------------------------------------

    def fetch_payload(
        self,
        payload_ref: PayloadRef | dict[str, Any],
    ) -> Iterator[NormalizedRecord]:
        """Resolve credentials, pick the right InputConnector, and stream
        NormalizedRecords for the chunk."""
        ref = self._coerce_payload(payload_ref)
        connector = self._registry.input_for(ref.type)
        creds = self._resolver.resolve(ref.credentials_ref)
        yield from connector.read(ref, creds=creds)

    # ----- output ---------------------------------------------------------

    def write_outputs(
        self,
        output_ref: OutputRef | dict[str, Any],
        records: Iterable[NormalizedRecord],
    ) -> int:
        """Resolve credentials, pick the right OutputConnector, and write."""
        ref = self._coerce_output(output_ref)
        connector = self._registry.output_for(ref.type)
        creds = self._resolver.resolve(ref.credentials_ref)
        return connector.write(ref, records, creds=creds)

    # ----- helpers --------------------------------------------------------

    @staticmethod
    def _coerce_payload(value: PayloadRef | dict[str, Any]) -> PayloadRef:
        if isinstance(value, PayloadRef):
            return value
        return PayloadRef.model_validate(value)

    @staticmethod
    def _coerce_output(value: OutputRef | dict[str, Any]) -> OutputRef:
        if isinstance(value, OutputRef):
            return value
        return OutputRef.model_validate(value)


# Top-level convenience for the common case (default registry, NullResolver).
# Applications that need scoped credentials should build a WorkerClient
# with a real resolver instead.


def fetch_payload(
    payload_ref: PayloadRef | dict[str, Any],
    *,
    registry: ConnectorRegistry | None = None,
    resolver: CredentialResolver | None = None,
) -> Iterator[NormalizedRecord]:
    return WorkerClient(registry, resolver).fetch_payload(payload_ref)


def write_outputs(
    output_ref: OutputRef | dict[str, Any],
    records: Iterable[NormalizedRecord],
    *,
    registry: ConnectorRegistry | None = None,
    resolver: CredentialResolver | None = None,
) -> int:
    return WorkerClient(registry, resolver).write_outputs(output_ref, records)
