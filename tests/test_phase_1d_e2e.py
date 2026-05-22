r"""End-to-end test of the full Phase 1d credentials lifecycle.

Reproduces the DATA_ARCHITECTURE.md §7 sequence in code:

    Orca mints credential (DevCredentialIssuer.issue)
        -> persists into Postgres (CredentialStore.put)
        -> indexes the user data source into PayloadRefs
        -> chunks carry credentials_ref

    Worker WorkerClient
        -> HttpCredentialResolver.resolve(credentials_ref)
            -> hits credentials_server (GET /credentials/<ref>)
            -> server reads CredentialStore, returns parsed payload
        -> connector.read(payload_ref, creds=resolved)
        -> NormalizedRecords flow to vLLM

This is the highest-confidence test of the Phase 1d contract: a real
uvicorn process on an ephemeral port, real httpx calls, real Postgres.

Requires \`make up\`.
"""

from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import uvicorn

from tandemn_system_data.clients import (
    DEFAULT_AUTH_HEADER,
    CredentialStore,
    PostgresClient,
    create_credentials_app,
)
from tandemn_system_data.db import Base, TenantRow
from tandemn_system_data.ids import new_tenant_id
from tandemn_user_data.connectors import LocalFileConnector
from tandemn_user_data.core import (
    ConnectorRegistry,
    HttpCredentialResolver,
)
from tandemn_user_data.orca import (
    DevCredentialIssuer,
    index_source,
)
from tandemn_user_data.worker import WorkerClient

pytestmark = pytest.mark.integration


WORKER_TOKEN = "phase-1d-e2e-token"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def pg_client() -> PostgresClient:
    return PostgresClient()


@pytest.fixture(scope="module", autouse=True)
def _reset_schema(pg_client: PostgresClient):
    Base.metadata.drop_all(pg_client.engine)
    with pg_client.engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    repo_root = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    yield


@pytest.fixture(scope="module")
def credentials_server(pg_client: PostgresClient) -> Iterator[str]:
    """Run the credentials FastAPI app on a real port in a background
    thread; yield the base URL; tear down on module exit."""
    store = CredentialStore(pg_client)
    app = create_credentials_app(store, auth_token=WORKER_TOKEN)
    port = _free_port()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    # Wait up to 5s for the server to come up.
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            r = httpx.get(
                f"{base_url}/healthz",
                headers={DEFAULT_AUTH_HEADER: WORKER_TOKEN},
                timeout=0.5,
            )
            if r.status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        raise RuntimeError("credentials server did not start")

    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# The §7 sequence end-to-end
# ---------------------------------------------------------------------------


def test_section_7_full_lifecycle_through_real_http(
    tmp_path: Path,
    pg_client: PostgresClient,
    credentials_server: str,
):
    # ----- 1. Set up some user data (file pretending to be an S3 bucket) ----
    input_path = tmp_path / "inputs.jsonl"
    with input_path.open("w") as f:
        for i in range(6):
            f.write(
                json.dumps(
                    {
                        "input_id": f"in_{i}",
                        "tenant_id": "tnt_1",
                        "job_id": "job_1",
                        "prompt": f"prompt {i}",
                    }
                )
            )
            f.write("\n")

    # ----- 2. Orca: persist a tenant and mint + persist a credential -------
    tenant_id = new_tenant_id()
    with pg_client.begin() as s:
        s.add(
            TenantRow(
                tenant_id=tenant_id,
                name="phase-1d-e2e",
                created_at=datetime.now(UTC),
            )
        )

    # Issuer holds the cleartext credential (in-memory only).
    issuer = DevCredentialIssuer()
    issued = issuer.issue(
        tenant_id=tenant_id,
        scope={"prefix": str(tmp_path)},
        # LocalFileConnector doesn't actually need creds — we still go
        # through the resolver to exercise the whole §7 path.
        secret_payload={"note": "phase-1d-e2e secret"},
    )

    # CredentialStore is the canonical persistence — Orca writes here.
    store = CredentialStore(pg_client)
    store.put(
        tenant_id=tenant_id,
        scope_json=issued.scope_json,
        # Serialize the secret_payload to JSON bytes per the new contract.
        secret_payload=json.dumps(issued.secret_payload).encode("utf-8"),
        expires_at=issued.expires_at,
        credentials_ref=issued.credentials_ref,
    )

    # ----- 3. Orca: index the source into PayloadRefs ----------------------
    registry = ConnectorRegistry()
    registry.register(LocalFileConnector())

    refs = list(
        index_source(
            {
                "type": "local",
                "uri": str(input_path),
                "format": "jsonl",
                "chunk_size_lines": 2,
            },
            registry=registry,
        )
    )
    # 6 lines / 2 -> 3 chunks
    assert len(refs) == 3

    # Orca attaches credentials_ref onto each PayloadRef before enqueue.
    enqueued = [ref.model_copy(update={"credentials_ref": issued.credentials_ref}) for ref in refs]

    # ----- 4. Worker: real HTTP-based resolver hitting the live server ----
    resolver = HttpCredentialResolver(
        base_url=credentials_server,
        token=WORKER_TOKEN,
    )
    # Sanity: directly resolving returns the parsed payload Orca minted.
    assert resolver.resolve(issued.credentials_ref) == {"note": "phase-1d-e2e secret"}

    worker = WorkerClient(registry=registry, resolver=resolver)

    # ----- 5. Worker: fetch every chunk and stitch the records back -------
    fetched = []
    for chunk in enqueued:
        fetched.extend(worker.fetch_payload(chunk.model_dump()))

    assert [r.input_id for r in fetched] == [f"in_{i}" for i in range(6)]
    assert [r.prompt for r in fetched] == [f"prompt {i}" for i in range(6)]


def test_expired_credential_fails_resolution(
    pg_client: PostgresClient,
    credentials_server: str,
):
    """If the credential the worker tries to resolve has expired,
    HttpCredentialResolver raises PermissionError. The §7 contract is
    that workers can't fetch with expired creds."""

    # Seed an expired credential.
    tenant_id = new_tenant_id()
    with pg_client.begin() as s:
        s.add(
            TenantRow(
                tenant_id=tenant_id,
                name="expired",
                created_at=datetime.now(UTC),
            )
        )

    store = CredentialStore(pg_client)
    ref = store.put(
        tenant_id=tenant_id,
        scope_json={},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    # Back-date.
    from sqlalchemy import text

    with pg_client.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE credentials SET expires_at = NOW() - INTERVAL '1 minute' "
                "WHERE credentials_ref = :ref"
            ),
            {"ref": ref},
        )

    resolver = HttpCredentialResolver(base_url=credentials_server, token=WORKER_TOKEN)
    with pytest.raises(PermissionError):
        resolver.resolve(ref)


def test_unauthorized_worker_token_is_rejected(credentials_server: str):
    """Even if a worker has the right credentials_ref string, it
    cannot fetch a credential without the worker token. §7: no
    anonymous resolution."""
    resolver = HttpCredentialResolver(
        base_url=credentials_server,
        token="totally-wrong-token",
    )
    with pytest.raises(PermissionError):
        resolver.resolve("cred_anything")
