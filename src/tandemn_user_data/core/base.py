"""Connector protocols and registry — DATA_ARCHITECTURE.md §7.

A connector for source type T implements:

  index(source_spec)        Orca-side: walk the source, emit one PayloadRef per chunk.
  read(payload_ref, creds)  worker-side: stream bytes, yield NormalizedRecords.
  write(output_ref, ...)    worker-side: append NormalizedRecords to the sink.

Registration is keyed by the `type` string in PayloadRef / OutputRef, so a
new data lake connector is one PR and zero schema migrations (principle 6).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any, Protocol, runtime_checkable

from tandemn_user_data.core.record import NormalizedRecord, OutputRef, PayloadRef


@runtime_checkable
class CredentialResolver(Protocol):
    """Resolves a credentials_ref to whatever the connector needs (e.g. an
    S3 access_key/secret_key dict). None is valid for credential-less
    connectors like local files."""

    def resolve(self, credentials_ref: str | None) -> Any | None: ...


@runtime_checkable
class InputConnector(Protocol):
    type: str  # registry key; must match PayloadRef.type

    def index(self, source_spec: dict[str, Any], creds: Any | None = None) -> Iterator[PayloadRef]:
        """Walk `source_spec` (the JSONB-shaped jobs.input_source) and emit
        one PayloadRef per chunk."""
        ...

    def read(
        self, payload_ref: PayloadRef, creds: Any | None = None
    ) -> Iterator[NormalizedRecord]: ...


@runtime_checkable
class OutputConnector(Protocol):
    type: str

    def write(
        self,
        output_ref: OutputRef,
        records: Iterable[NormalizedRecord],
        creds: Any | None = None,
    ) -> int:
        """Persist `records` at `output_ref`. Returns the count written."""
        ...


class ConnectorRegistry:
    """Connector lookup by `type` string. A connector may implement both
    sides (the common case)."""

    def __init__(self) -> None:
        self._inputs: dict[str, InputConnector] = {}
        self._outputs: dict[str, OutputConnector] = {}

    def register(self, connector: Any) -> None:
        if not getattr(connector, "type", None):
            raise ValueError("connector.type must be a non-empty string")
        registered = False
        if isinstance(connector, InputConnector):
            self._inputs[connector.type] = connector
            registered = True
        if isinstance(connector, OutputConnector):
            self._outputs[connector.type] = connector
            registered = True
        if not registered:
            raise TypeError(f"{connector!r} implements neither connector protocol")

    def input_for(self, type_: str) -> InputConnector:
        try:
            return self._inputs[type_]
        except KeyError as e:
            raise KeyError(
                f"No InputConnector registered for type={type_!r}. "
                f"Registered: {sorted(self._inputs)}"
            ) from e

    def output_for(self, type_: str) -> OutputConnector:
        try:
            return self._outputs[type_]
        except KeyError as e:
            raise KeyError(
                f"No OutputConnector registered for type={type_!r}. "
                f"Registered: {sorted(self._outputs)}"
            ) from e
