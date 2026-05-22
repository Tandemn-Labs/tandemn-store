"""Narrow HTTP server for credential resolution — DATA_ARCHITECTURE.md §7.

Workers call `GET /credentials/<ref>` to resolve a credentials_ref to
the opaque secret payload Orca minted for that ref. In production this
endpoint is folded into Orca's main FastAPI app; here it ships as a
factory function so the same code path is used in tests and in Orca.

Auth: §7 says \"mTLS or signed worker identity\". Per §11 \"Out of scope\",
real mTLS / KMS / Vault integration is deferred (Phase 1d ships a
shared-secret bearer header as a stand-in). The auth surface is small
and pluggable so swapping in mTLS later is a single change.

Response shape:
  {
    \"credentials_ref\": \"cred_...\",
    \"tenant_id\":       \"tnt_...\",
    \"scope_json\":      {...},
    \"secret_payload\":  base64-encoded bytes,
    \"expires_at\":      ISO-8601 timestamp,
  }

The worker decodes `secret_payload` from base64 and passes it (or a
parsed form of it) to the connector as `creds`.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from tandemn_system_data.clients.credentials_store import (
    CredentialExpired,
    CredentialNotFound,
    CredentialStore,
)

DEFAULT_AUTH_HEADER = "X-Tandemn-Worker-Token"


def create_credentials_app(
    store: CredentialStore,
    *,
    auth_token: str | None = None,
    auth_header: str = DEFAULT_AUTH_HEADER,
) -> FastAPI:
    """Build a minimal FastAPI app exposing GET /credentials/<ref>.

    Args:
        store:        The CredentialStore backing this endpoint.
        auth_token:   Shared-secret token a worker must present.
                      If None, falls back to the
                      TANDEMN_WORKER_TOKEN env var. If both are unset,
                      the endpoint refuses to start — the doc \u00a77 rule
                      is no anonymous resolution, ever.
        auth_header:  HTTP header that carries the token.
    """
    resolved_token = auth_token or os.getenv("TANDEMN_WORKER_TOKEN")
    if not resolved_token:
        raise RuntimeError(
            "create_credentials_app requires auth_token or TANDEMN_WORKER_TOKEN; "
            "anonymous credential resolution is not allowed (DATA_ARCHITECTURE.md \u00a77)."
        )

    app = FastAPI(title="tandemn-credentials", version="0.1.0")

    @app.middleware("http")
    async def _require_token(
        request: Request,
        call_next: Callable[[Request], Awaitable[JSONResponse]],
    ):
        if request.headers.get(auth_header) != resolved_token:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/credentials/{credentials_ref}")
    def get_credential(credentials_ref: str) -> dict:
        try:
            row = store.get(credentials_ref)
        except CredentialNotFound as e:
            raise HTTPException(status_code=404, detail="credential not found") from e
        except CredentialExpired as e:
            raise HTTPException(status_code=410, detail="credential expired") from e

        return {
            "credentials_ref": row.credentials_ref,
            "tenant_id": row.tenant_id,
            "scope_json": row.scope_json,
            "secret_payload": base64.b64encode(row.secret_payload).decode("ascii"),
            "expires_at": row.expires_at.isoformat(),
        }

    return app
