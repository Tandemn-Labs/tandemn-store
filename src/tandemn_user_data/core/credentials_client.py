"""Worker-side credential resolution — DATA_ARCHITECTURE.md §7.

Per the doc, workers NEVER hold long-lived customer credentials. They
resolve a `credentials_ref` at fetch time, typically by calling Orca's
narrow GET /credentials/<ref> endpoint over mTLS.

In Phase 1c we ship two simple implementations:

  LocalCredentialsCache  in-memory map; used by tests and dev workflows.
  NullResolver           always returns None; for connectors that don't
                         need credentials (e.g. LocalFileConnector).

A real HTTP-backed resolver (talking to Orca) will land in Phase 1d
when Orca exposes the endpoint.
"""

from __future__ import annotations

from typing import Any


class NullResolver:
    """Returns None for every credentials_ref. Useful for tests and
    connectors that don't need credentials."""

    def resolve(self, credentials_ref: str | None) -> Any | None:  # noqa: ARG002
        return None


class LocalCredentialsCache:
    """In-memory credential resolver for tests and dev.

    Mirrors what Orca's CredentialIssuer hands out: a `credentials_ref`
    key mapped to whatever opaque value the consuming connector expects.

    For S3:   {"access_key": "...", "secret_key": "...", "endpoint": "..."}
    For local: not needed; LocalFileConnector ignores creds.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def put(self, credentials_ref: str, value: Any) -> None:
        if not credentials_ref:
            raise ValueError("credentials_ref must be a non-empty string")
        self._store[credentials_ref] = value

    def resolve(self, credentials_ref: str | None) -> Any | None:
        if credentials_ref is None:
            return None
        if credentials_ref not in self._store:
            raise KeyError(
                f"credentials_ref={credentials_ref!r} not in local cache. "
                f"Known: {sorted(self._store)}"
            )
        return self._store[credentials_ref]
