"""CredentialStore — Postgres-backed access to the `credentials` table.

Per DATA_ARCHITECTURE.md §5 and §7:

  - Orca mints short-lived, scoped credentials per job.
  - The minted credential is persisted to the `credentials` table.
  - Workers resolve `credentials_ref` to a token via a narrow Orca
    HTTP endpoint (mTLS).

This module is the canonical-store side of that lifecycle: persistence,
lookup, and expiry handling. It deliberately takes primitive arguments
instead of an IssuedCredential so tandemn_system_data has zero coupling
to tandemn_user_data. Orca (which imports both) is the place that
translates one to the other.

The endpoint server (clients/credentials_server.py) sits on top of this
store. Workers never call CredentialStore directly — they go through
HTTP via tandemn_user_data.core.credentials_client.HttpCredentialResolver.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from tandemn_system_data.clients.postgres import PostgresClient
from tandemn_system_data.db import CredentialsRow
from tandemn_system_data.ids import new_credentials_ref


class CredentialNotFound(KeyError):
    """Raised when a credentials_ref is not in the store."""


class CredentialExpired(LookupError):
    """Raised when a credentials_ref exists but has passed its expires_at."""


class CredentialStore:
    """Read/write access to the canonical `credentials` table."""

    def __init__(self, pg: PostgresClient) -> None:
        self._pg = pg

    # -- writes -----------------------------------------------------------

    def put(
        self,
        *,
        tenant_id: str,
        scope_json: dict[str, Any],
        secret_payload: bytes,
        expires_at: datetime,
        rotated_from: str | None = None,
        credentials_ref: str | None = None,
    ) -> str:
        """Persist a credential and return its credentials_ref.

        Args:
            tenant_id        canonical tenant ID
            scope_json       JSONB scope object (e.g. {"prefix": "s3://..."})
            secret_payload   raw bytes; in production these would be
                             encrypted at rest via pgcrypto or KMS
            expires_at       tz-aware UTC datetime in the future
            rotated_from     optional credentials_ref this one replaces
            credentials_ref  caller-supplied ref; generated if None

        Returns the credentials_ref that was written.
        """
        if expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        if expires_at <= datetime.now(UTC):
            raise ValueError("expires_at must be in the future")
        if not isinstance(secret_payload, (bytes, bytearray, memoryview)):
            raise TypeError("secret_payload must be bytes")

        ref = credentials_ref or new_credentials_ref()
        now = datetime.now(UTC)

        with self._pg.begin() as s:
            s.add(
                CredentialsRow(
                    credentials_ref=ref,
                    tenant_id=tenant_id,
                    scope_json=scope_json,
                    secret_payload=bytes(secret_payload),
                    expires_at=expires_at,
                    rotated_from=rotated_from,
                    created_at=now,
                )
            )
        return ref

    # -- reads ------------------------------------------------------------

    def get(self, credentials_ref: str) -> CredentialsRow:
        """Look up a credential by ref.

        Raises:
            CredentialNotFound if the ref does not exist.
            CredentialExpired  if the ref exists but expires_at <= now.
        """
        with self._pg.session() as s:
            row = s.get(CredentialsRow, credentials_ref)
            if row is None:
                raise CredentialNotFound(credentials_ref)
            if row.expires_at <= datetime.now(UTC):
                raise CredentialExpired(credentials_ref)
            # Detach so it's safe to use after the session closes.
            s.expunge(row)
            return row

    def exists(self, credentials_ref: str) -> bool:
        try:
            self.get(credentials_ref)
            return True
        except (CredentialNotFound, CredentialExpired):
            return False

    def list_for_tenant(
        self,
        tenant_id: str,
        *,
        include_expired: bool = False,
    ) -> list[CredentialsRow]:
        """All credentials issued to a tenant. Useful for ops and audit."""
        now = datetime.now(UTC)
        with self._pg.session() as s:
            stmt = select(CredentialsRow).where(CredentialsRow.tenant_id == tenant_id)
            if not include_expired:
                stmt = stmt.where(CredentialsRow.expires_at > now)
            rows = list(s.execute(stmt).scalars())
            for r in rows:
                s.expunge(r)
            return rows

    # -- maintenance ------------------------------------------------------

    def revoke(self, credentials_ref: str) -> bool:
        """Hard-delete a credential. Returns True if anything was removed."""
        with self._pg.begin() as s:
            row = s.get(CredentialsRow, credentials_ref)
            if row is None:
                return False
            s.delete(row)
            return True

    def purge_expired(self, *, before: datetime | None = None) -> int:
        """Delete all credentials with expires_at <= `before` (default now).

        Returns the number of rows deleted.
        """
        cutoff = before or datetime.now(UTC)
        with self._pg.begin() as s:
            stmt = select(CredentialsRow).where(CredentialsRow.expires_at <= cutoff)
            rows: Iterable[CredentialsRow] = s.execute(stmt).scalars().all()
            count = 0
            for row in rows:
                s.delete(row)
                count += 1
            return count
