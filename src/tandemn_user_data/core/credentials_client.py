"""Worker-side credential resolution — DATA_ARCHITECTURE.md §7.

Per the doc, workers NEVER hold long-lived customer credentials. They
resolve a `credentials_ref` at fetch time, typically by calling Orca's
narrow GET /credentials/<ref> endpoint over mTLS.

Three implementations ship in this module:

  NullResolver           always returns None; for connectors that don't
                         need credentials (e.g. LocalFileConnector).
  LocalCredentialsCache  in-memory map; used by tests and dev workflows.
  HttpCredentialResolver real worker-side resolver: GETs the parsed
                         secret_payload from the credentials endpoint.

HttpCredentialResolver does NOT import anything from tandemn_system_data
— the worker side of the user-data boundary stays clean (\u00a71 principle 2).
"""

from __future__ import annotations

from typing import Any

import httpx


class NullResolver:
    """Returns None for every credentials_ref. Useful for tests and
    connectors that don't need credentials."""

    def resolve(self, credentials_ref: str | None) -> Any | None:  # noqa: ARG002
        return None


_DEFAULT_AUTH_HEADER = "X-Tandemn-Worker-Token"


class HttpCredentialResolver:
    """Worker-side resolver that hits the Orca credentials endpoint.

    Uses httpx with a bounded timeout and a small in-process cache so
    repeated lookups for the same ref within one process don't
    re-hit the server.

    Construction:
        resolver = HttpCredentialResolver(
            base_url="https://orca.internal",
            token="<worker bearer token>",
        )

    Returns the parsed `secret_payload` field from the endpoint
    response (a dict, list, str, or None depending on what Orca
    minted). Returns None when the credentials_ref is itself None.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        auth_header: str = _DEFAULT_AUTH_HEADER,
        timeout: float = 5.0,
        cache_responses: bool = True,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not token:
            raise ValueError("token is required (anonymous resolution is not allowed)")
        self._base_url = base_url.rstrip("/")
        self._headers = {auth_header: token}
        self._timeout = timeout
        self._cache_responses = cache_responses
        self._cache: dict[str, Any] = {}

    # CredentialResolver protocol
    def resolve(self, credentials_ref: str | None) -> Any | None:
        if credentials_ref is None:
            return None
        if self._cache_responses and credentials_ref in self._cache:
            return self._cache[credentials_ref]

        url = f"{self._base_url}/credentials/{credentials_ref}"
        resp = httpx.get(url, headers=self._headers, timeout=self._timeout)

        if resp.status_code == 404:
            raise KeyError(f"credentials_ref={credentials_ref!r} not found")
        if resp.status_code == 410:
            raise PermissionError(f"credentials_ref={credentials_ref!r} expired")
        if resp.status_code == 401:
            raise PermissionError("worker token not accepted by credentials endpoint")
        if resp.status_code >= 400:
            raise RuntimeError(
                f"credentials endpoint returned {resp.status_code}: {resp.text[:200]}"
            )

        secret_payload = resp.json().get("secret_payload")
        if self._cache_responses:
            self._cache[credentials_ref] = secret_payload
        return secret_payload


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
