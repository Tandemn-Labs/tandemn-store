"""Orca-side credential issuer — DATA_ARCHITECTURE.md §7 and §11.

Per §7, Orca mints short-lived, scoped credentials per job. Workers
resolve `credentials_ref` to a usable token at fetch time via a
narrow Orca endpoint (mTLS).

Per §11 \"Out of scope\", real STS / KMS / Vault integration is
deferred. This module ships the dev-mode issuer used by Phase 1c:
an in-memory store paired with the LocalCredentialsCache resolver.

  IssuedCredential   the value the issuer returns: a credentials_ref
                     plus an opaque secret payload + scope + expiry.

  DevCredentialIssuer
      .issue(tenant_id, scope, secret_payload, ttl_seconds) -> IssuedCredential
      .bind_to_cache(cache)  populate a LocalCredentialsCache with all
                             currently-issued credentials. Lets a worker
                             in the same process resolve refs without
                             going through HTTP.

Real-Orca wiring (Phase 1d) will persist IssuedCredentials to the
`credentials` table in tandemn_system_data and serve them over HTTP.
That code lives in Orca, not here — tandemn_user_data must stay
unaware of the canonical store.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from tandemn_user_data.core import LocalCredentialsCache

DEFAULT_TTL_SECONDS = 3600  # 1 hour
_DEV_REF_PREFIX = "cred_"


def _new_dev_ref() -> str:
    """Generate a dev-mode credentials_ref.

    We do NOT import tandemn_system_data.ids here — that would couple
    the user-data path to the system-data path. The format is
    intentionally compatible (prefix + opaque body) so the same string
    works as a stand-in until Orca's real wiring takes over.
    """
    return f"{_DEV_REF_PREFIX}{secrets.token_hex(13)}"


@dataclass
class IssuedCredential:
    """Output of DevCredentialIssuer.issue().

    Mirrors the shape of a row in the `credentials` table without
    importing the ORM. Orca translates IssuedCredential -> CredentialsRow
    when it persists.
    """

    credentials_ref: str
    tenant_id: str
    scope_json: dict[str, Any]
    secret_payload: Any
    expires_at: datetime
    rotated_from: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class DevCredentialIssuer:
    """In-memory credentials issuer for tests, demos, and the Phase 1c
    sandbox. NOT for production — there's no rotation, no revocation,
    and the \"secret\" is whatever the caller passes in.

    Usage:
        issuer = DevCredentialIssuer()
        issued = issuer.issue(
            tenant_id="tnt_1",
            scope={"prefix": "s3://customer/inputs/"},
            secret_payload={"access_key": "k", "secret_key": "s"},
        )
        # ... write issued.credentials_ref into the chunk's PayloadRef
        cache = LocalCredentialsCache()
        issuer.bind_to_cache(cache)
        # ... worker resolves issued.credentials_ref via cache
    """

    def __init__(self) -> None:
        self._store: dict[str, IssuedCredential] = {}

    # -- issuance ----------------------------------------------------------

    def issue(
        self,
        tenant_id: str,
        scope: dict[str, Any],
        secret_payload: Any,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        rotated_from: str | None = None,
    ) -> IssuedCredential:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")

        ref = _new_dev_ref()
        now = datetime.now(UTC)
        issued = IssuedCredential(
            credentials_ref=ref,
            tenant_id=tenant_id,
            scope_json=scope,
            secret_payload=secret_payload,
            expires_at=now + timedelta(seconds=ttl_seconds),
            rotated_from=rotated_from,
            created_at=now,
        )
        self._store[ref] = issued
        return issued

    # -- lookup ------------------------------------------------------------

    def get(self, credentials_ref: str) -> IssuedCredential | None:
        return self._store.get(credentials_ref)

    def __iter__(self) -> Iterator[IssuedCredential]:
        return iter(self._store.values())

    def __len__(self) -> int:
        return len(self._store)

    # -- worker bridge -----------------------------------------------------

    def bind_to_cache(self, cache: LocalCredentialsCache) -> None:
        """Copy every currently-issued credential into a worker's
        LocalCredentialsCache so worker code in the same process can
        resolve refs without going through HTTP.

        Only the secret_payload is exposed to the worker — the rest of
        IssuedCredential is Orca-side metadata.
        """
        for issued in self._store.values():
            cache.put(issued.credentials_ref, issued.secret_payload)
