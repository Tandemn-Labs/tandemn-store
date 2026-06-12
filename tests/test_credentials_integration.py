"""Integration: credentials lifecycle — store, server, worker resolver,
end-to-end through real HTTP per DATA_ARCHITECTURE.md §7.
Requires Postgres (`make up`)."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import uvicorn
from sqlalchemy import text

from tandemn_system_data.clients import (
    DEFAULT_AUTH_HEADER,
    CredentialExpired,
    CredentialNotFound,
    CredentialStore,
    PostgresClient,
    create_credentials_app,
)
from tandemn_system_data.db import UserRow
from tandemn_system_data.ids import new_user_id
from tandemn_user_data.core import ConnectorRegistry, HttpCredentialResolver
from tandemn_user_data.orca import index_source
from tandemn_user_data.worker import WorkerClient
from tests.local_connector import LocalFileConnector

pytestmark = pytest.mark.integration

WORKER_TOKEN = "credentials-e2e-token"


@pytest.fixture(scope="module", autouse=True)
def _schema(fresh_schema):
    pass


@pytest.fixture
def store(pg_client: PostgresClient) -> CredentialStore:
    return CredentialStore(pg_client)


@pytest.fixture
def user_id(pg_client: PostgresClient) -> str:
    uid = new_user_id()
    with pg_client.begin() as s:
        s.add(UserRow(user_id=uid, name="creds-test", created_at=datetime.now(UTC)))
    return uid


def _expire(pg_client: PostgresClient, ref: str) -> None:
    with pg_client.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE credentials SET expires_at = NOW() - INTERVAL '1 minute' "
                "WHERE credentials_ref = :ref"
            ),
            {"ref": ref},
        )


# ----- CredentialStore --------------------------------------------------------


def test_put_get_round_trip_and_validation(store: CredentialStore, user_id: str):
    ref = store.put(
        user_id=user_id,
        scope_json={"prefix": "s3://customer/inputs/"},
        secret_payload=b'"opaque"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    row = store.get(ref)
    assert row.secret_payload == b'"opaque"' and row.user_id == user_id

    with pytest.raises(ValueError):  # naive datetime
        store.put(
            user_id=user_id,
            scope_json={},
            secret_payload=b'"x"',
            expires_at=datetime.now() + timedelta(hours=1),
        )
    with pytest.raises(ValueError):  # secret must be UTF-8 JSON
        store.put(
            user_id=user_id,
            scope_json={},
            secret_payload=b"\xff\xfe-not-json",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )


def test_expiry_revoke_and_purge(store: CredentialStore, user_id: str, pg_client: PostgresClient):
    ref = store.put(
        user_id=user_id,
        scope_json={},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    _expire(pg_client, ref)
    with pytest.raises(CredentialExpired):
        store.get(ref)
    assert store.exists(ref) is False
    assert store.purge_expired() >= 1

    live = store.put(
        user_id=user_id,
        scope_json={},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert store.revoke(live) is True
    assert store.revoke(live) is False  # idempotent
    with pytest.raises(CredentialNotFound):
        store.get(live)


# ----- End-to-end through real HTTP (§7) --------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def credentials_server(pg_client: PostgresClient, _schema) -> Iterator[str]:
    """Run the credentials FastAPI app on a real port in a background thread."""
    app = create_credentials_app(CredentialStore(pg_client), auth_token=WORKER_TOKEN)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            if (
                httpx.get(
                    f"{base_url}/healthz",
                    headers={DEFAULT_AUTH_HEADER: WORKER_TOKEN},
                    timeout=0.5,
                ).status_code
                == 200
            ):
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


def test_full_lifecycle_through_real_http(
    tmp_path: Path, store: CredentialStore, user_id: str, credentials_server: str
):
    """Orca mints a credential and indexes the source; the worker resolves
    the ref over HTTP and fetches every chunk."""
    input_path = tmp_path / "inputs.jsonl"
    with input_path.open("w") as f:
        for i in range(6):
            f.write(
                json.dumps(
                    {
                        "input_id": f"in_{i}",
                        "user_id": user_id,
                        "job_id": "job_1",
                        "prompt": f"prompt {i}",
                    }
                )
                + "\n"
            )

    secret = {"note": "e2e secret"}
    ref = store.put(
        user_id=user_id,
        scope_json={"prefix": str(tmp_path)},
        secret_payload=json.dumps(secret).encode("utf-8"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    registry = ConnectorRegistry()
    registry.register(LocalFileConnector())
    refs = list(
        index_source(
            {"type": "local", "uri": str(input_path), "chunk_size_lines": 2},
            registry=registry,
        )
    )
    enqueued = [r.model_copy(update={"credentials_ref": ref}) for r in refs]

    resolver = HttpCredentialResolver(base_url=credentials_server, token=WORKER_TOKEN)
    assert resolver.resolve(ref) == secret

    worker = WorkerClient(registry=registry, resolver=resolver)
    fetched = [rec for chunk in enqueued for rec in worker.fetch_payload(chunk.model_dump())]
    assert [r.input_id for r in fetched] == [f"in_{i}" for i in range(6)]


def test_expired_and_unauthorized_resolution_fail(
    store: CredentialStore, user_id: str, pg_client: PostgresClient, credentials_server: str
):
    ref = store.put(
        user_id=user_id,
        scope_json={},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    _expire(pg_client, ref)
    with pytest.raises(PermissionError):  # 410
        HttpCredentialResolver(base_url=credentials_server, token=WORKER_TOKEN).resolve(ref)
    with pytest.raises(PermissionError):  # 401: no anonymous resolution
        HttpCredentialResolver(base_url=credentials_server, token="wrong-token").resolve(ref)
