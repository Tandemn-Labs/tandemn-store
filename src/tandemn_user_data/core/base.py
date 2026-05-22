"""Connector protocols and registry — DATA_ARCHITECTURE.md §7.

An InputConnector / OutputConnector for source type `T` knows how to:

  index(source_spec)       (Orca, before launch) walk the source and
                           emit one PayloadRef per chunk.
  read(payload_ref, creds) (worker, at execution time) stream the
                           bytes referenced by a PayloadRef and yield
                           NormalizedRecords.
  write(output_ref, ...)   (worker, at execution time) append
                           NormalizedRecords to the output sink.

Per principle 6: a new data lake connector is one PR. Registration is
keyed by the `type` string in PayloadRef / OutputRef, so the rest of
the system stays source-agnostic.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any, Protocol, runtime_checkable

from tandemn_user_data.core.record import NormalizedRecord, OutputRef, PayloadRef

# ---------------------------------------------------------------------------
# Credential resolution (worker-side)
# ---------------------------------------------------------------------------


@runtime_checkable
class CredentialResolver(Protocol):
    """Worker-side credential resolver.

    Resolves a `credentials_ref` to whatever opaque object the
    underlying connector needs (e.g. an AWS access_key/secret_key dict
    for S3, a Snowflake login dict, ...). Implementations:

      - Production: call Orca's narrow GET /credentials/<ref> over mTLS.
      - Tests / dev: in-memory cache, see worker.LocalCredentialsCache.

    Returning None is valid for connectors that don't need credentials
    (e.g. local filesystem).
    """

    def resolve(self, credentials_ref: str | None) -> Any | None: ...


# ---------------------------------------------------------------------------
# Connector protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class InputConnector(Protocol):
    """Read side of a data source.

    Implementations live under tandemn_user_data/connectors/.
    """

    type: str  # the registry key; must match PayloadRef.type

    def index(
        self,
        source_spec: dict[str, Any],
        creds: Any | None = None,
    ) -> Iterator[PayloadRef]:
        """Walk a source and emit one PayloadRef per chunk.

        `source_spec` is the JSONB-shaped `input_source` from jobs.
        Connectors are free to define their own keys inside it.
        """
        ...

    def read(
        self,
        payload_ref: PayloadRef,
        creds: Any | None = None,
    ) -> Iterator[NormalizedRecord]:
        """Stream the bytes pointed to by `payload_ref` and yield NormalizedRecords."""
        ...


@runtime_checkable
class OutputConnector(Protocol):
    """Write side of a data sink."""

    type: str

    def write(
        self,
        output_ref: OutputRef,
        records: Iterable[NormalizedRecord],
        creds: Any | None = None,
    ) -> int:
        """Persist `records` at the location described by `output_ref`.

        Returns the number of records written. Connectors may stream
        in batches internally.
        """
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ConnectorRegistry:
    """Lookup of connector implementations by `type` string.

    A single connector class is allowed to register as both an
    InputConnector and an OutputConnector (the common case for S3 /
    local file).
    """

    def __init__(self) -> None:
        self._inputs: dict[str, InputConnector] = {}
        self._outputs: dict[str, OutputConnector] = {}

    # -- registration -------------------------------------------------

    def register_input(self, connector: InputConnector) -> None:
        if not getattr(connector, "type", None):
            raise ValueError("connector.type must be a non-empty string")
        self._inputs[connector.type] = connector

    def register_output(self, connector: OutputConnector) -> None:
        if not getattr(connector, "type", None):
            raise ValueError("connector.type must be a non-empty string")
        self._outputs[connector.type] = connector

    def register(self, connector: Any) -> None:
        """Convenience: register as both input and output if applicable."""
        if isinstance(connector, InputConnector):
            self.register_input(connector)
        if isinstance(connector, OutputConnector):
            self.register_output(connector)

    # -- lookup -------------------------------------------------------

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

    def known_input_types(self) -> list[str]:
        return sorted(self._inputs)

    def known_output_types(self) -> list[str]:
        return sorted(self._outputs)
