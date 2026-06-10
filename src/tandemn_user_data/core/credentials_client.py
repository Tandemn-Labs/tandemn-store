"""Worker-side credential resolution — DATA_ARCHITECTURE.md §7.

Workers never hold long-lived customer credentials. They resolve a
credentials_ref at fetch time via Orca's narrow GET /credentials/<ref>.

Responses are deliberately NOT cached: credentials are short-lived and
the server enforces expiry (410). A cache would hand out secrets past
their expires_at.

This module must not import tandemn_system_data (§1 principle 2).
"""

from __future__ import annotations

from typing import Any

import httpx


class NullResolver:
    """Returns None for every ref. For tests and credential-less connectors."""

    def resolve(self, credentials_ref: str | None) -> Any | None:  # noqa: ARG002
        return None


_DEFAULT_AUTH_HEADER = "X-Tandemn-Worker-Token"


class HttpCredentialResolver:
    """Resolves a credentials_ref against the Orca credentials endpoint.

    Returns the parsed `secret_payload` from the response, or None when
    the ref itself is None.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        auth_header: str = _DEFAULT_AUTH_HEADER,
        timeout: float = 5.0,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not token:
            raise ValueError("token is required (anonymous resolution is not allowed)")
        self._base_url = base_url.rstrip("/")
        self._headers = {auth_header: token}
        self._timeout = timeout

    def resolve(self, credentials_ref: str | None) -> Any | None:
        if credentials_ref is None:
            return None

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

        return resp.json().get("secret_payload")
