r"""Tests for the /credentials/<ref> FastAPI app.

Requires \`make up\` (the store is Postgres-backed). Uses httpx's
ASGITransport to talk to the app in-process without binding a port.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tandemn_system_data.clients import (
    DEFAULT_AUTH_HEADER,
    CredentialStore,
    PostgresClient,
    create_credentials_app,
)
from tandemn_system_data.db import Base, TenantRow
from tandemn_system_data.ids import new_tenant_id

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


WORKER_TOKEN = "worker-dev-token"


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


@pytest.fixture
def store(pg_client: PostgresClient) -> CredentialStore:
    return CredentialStore(pg_client)


@pytest.fixture
def tenant_id(pg_client: PostgresClient) -> str:
    tid = new_tenant_id()
    with pg_client.begin() as s:
        s.add(TenantRow(tenant_id=tid, name="srv-test", created_at=datetime.now(UTC)))
    return tid


@pytest.fixture
def client(store: CredentialStore) -> TestClient:
    app = create_credentials_app(store, auth_token=WORKER_TOKEN)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_app_construction_requires_token(store: CredentialStore, monkeypatch):
    monkeypatch.delenv("TANDEMN_WORKER_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        create_credentials_app(store)


def test_app_construction_uses_env_token(store: CredentialStore, monkeypatch):
    monkeypatch.setenv("TANDEMN_WORKER_TOKEN", "from-env")
    app = create_credentials_app(store)  # should not raise
    assert app.title == "tandemn-credentials"


def test_healthz_requires_token(client: TestClient):
    r = client.get("/healthz")
    assert r.status_code == 401
    r = client.get("/healthz", headers={DEFAULT_AUTH_HEADER: WORKER_TOKEN})
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_get_credential_round_trip(client: TestClient, store: CredentialStore, tenant_id: str):
    creds_dict = {"access_key": "AKIAEXAMPLE", "secret_key": "very-secret"}
    ref = store.put(
        tenant_id=tenant_id,
        scope_json={"prefix": "s3://customer/inputs/"},
        secret_payload=json.dumps(creds_dict).encode("utf-8"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    r = client.get(
        f"/credentials/{ref}",
        headers={DEFAULT_AUTH_HEADER: WORKER_TOKEN},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["credentials_ref"] == ref
    assert body["tenant_id"] == tenant_id
    assert body["scope_json"] == {"prefix": "s3://customer/inputs/"}
    # secret_payload arrives as the parsed JSON object — ready to hand to a connector.
    assert body["secret_payload"] == creds_dict
    # expires_at is ISO-8601
    parsed = datetime.fromisoformat(body["expires_at"])
    assert parsed > datetime.now(UTC)


def test_unauthorized_without_token(client: TestClient, store: CredentialStore, tenant_id: str):
    ref = store.put(
        tenant_id=tenant_id,
        scope_json={},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    r = client.get(f"/credentials/{ref}")
    assert r.status_code == 401


def test_unauthorized_with_wrong_token(client: TestClient, store: CredentialStore, tenant_id: str):
    ref = store.put(
        tenant_id=tenant_id,
        scope_json={},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    r = client.get(
        f"/credentials/{ref}",
        headers={DEFAULT_AUTH_HEADER: "wrong-token"},
    )
    assert r.status_code == 401


def test_unknown_ref_returns_404(client: TestClient):
    r = client.get(
        "/credentials/cred_does_not_exist",
        headers={DEFAULT_AUTH_HEADER: WORKER_TOKEN},
    )
    assert r.status_code == 404


def test_expired_ref_returns_410(
    client: TestClient,
    store: CredentialStore,
    tenant_id: str,
    pg_client: PostgresClient,
):
    ref = store.put(
        tenant_id=tenant_id,
        scope_json={},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    # Back-date.
    with pg_client.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE credentials SET expires_at = NOW() - INTERVAL '1 minute' "
                "WHERE credentials_ref = :ref"
            ),
            {"ref": ref},
        )
    r = client.get(
        f"/credentials/{ref}",
        headers={DEFAULT_AUTH_HEADER: WORKER_TOKEN},
    )
    assert r.status_code == 410
