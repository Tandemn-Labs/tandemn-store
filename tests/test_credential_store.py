r"""Integration tests for CredentialStore.

Requires \`make up\`. Exercises the canonical-store side of credential
persistence per DATA_ARCHITECTURE.md §5 / §7.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from tandemn_system_data.clients import (
    CredentialExpired,
    CredentialNotFound,
    CredentialStore,
    PostgresClient,
)
from tandemn_system_data.db import Base
from tandemn_system_data.ids import new_tenant_id

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_client() -> PostgresClient:
    return PostgresClient()


@pytest.fixture(scope="module", autouse=True)
def _reset_schema(pg_client: PostgresClient):
    """Reapply the Alembic baseline before this module runs."""
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
def seeded_tenant(pg_client: PostgresClient) -> str:
    """Insert a tenant for FK satisfaction; return its id."""
    from tandemn_system_data.db import TenantRow

    tid = new_tenant_id()
    now = datetime.now(UTC)
    with pg_client.begin() as s:
        s.add(TenantRow(tenant_id=tid, name="creds-test", created_at=now))
    return tid


# ---------------------------------------------------------------------------
# put / get
# ---------------------------------------------------------------------------


def test_put_returns_credentials_ref(store: CredentialStore, seeded_tenant: str):
    ref = store.put(
        tenant_id=seeded_tenant,
        scope_json={"prefix": "s3://customer/inputs/"},
        secret_payload=b'"opaque-token-bytes"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert ref.startswith("cred_")


def test_put_then_get_round_trip(store: CredentialStore, seeded_tenant: str):
    ref = store.put(
        tenant_id=seeded_tenant,
        scope_json={"prefix": "s3://customer/inputs/"},
        secret_payload=b'"opaque"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    row = store.get(ref)
    assert row.credentials_ref == ref
    assert row.tenant_id == seeded_tenant
    assert row.scope_json == {"prefix": "s3://customer/inputs/"}
    assert row.secret_payload == b'"opaque"'


def test_put_accepts_caller_supplied_ref(store: CredentialStore, seeded_tenant: str):
    ref = "cred_my_dev_handle"
    returned = store.put(
        tenant_id=seeded_tenant,
        scope_json={},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        credentials_ref=ref,
    )
    assert returned == ref
    assert store.get(ref).credentials_ref == ref


def test_put_rejects_naive_expires_at(store: CredentialStore, seeded_tenant: str):
    with pytest.raises(ValueError):
        store.put(
            tenant_id=seeded_tenant,
            scope_json={},
            secret_payload=b'"x"',
            expires_at=datetime.now() + timedelta(hours=1),  # naive on purpose
        )


def test_put_rejects_past_expires_at(store: CredentialStore, seeded_tenant: str):
    with pytest.raises(ValueError):
        store.put(
            tenant_id=seeded_tenant,
            scope_json={},
            secret_payload=b'"x"',
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )


def test_put_rejects_non_bytes_secret(store: CredentialStore, seeded_tenant: str):
    with pytest.raises(TypeError):
        store.put(
            tenant_id=seeded_tenant,
            scope_json={},
            secret_payload="not-bytes",  # type: ignore[arg-type]
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )


def test_put_rejects_non_json_secret(store: CredentialStore, seeded_tenant: str):
    """secret_payload must be UTF-8 JSON so the resolver endpoint can
    serve it as a parsed object."""
    with pytest.raises(ValueError):
        store.put(
            tenant_id=seeded_tenant,
            scope_json={},
            secret_payload=b"\xff\xfe-not-json-and-not-utf8",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )


# ---------------------------------------------------------------------------
# Expiry semantics
# ---------------------------------------------------------------------------


def test_get_rejects_expired(store: CredentialStore, seeded_tenant: str, pg_client: PostgresClient):
    # Insert a credential, then back-date its expires_at via direct SQL.
    ref = store.put(
        tenant_id=seeded_tenant,
        scope_json={},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    with pg_client.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE credentials SET expires_at = NOW() - INTERVAL '1 minute' "
                "WHERE credentials_ref = :ref"
            ),
            {"ref": ref},
        )
    with pytest.raises(CredentialExpired):
        store.get(ref)


def test_get_unknown_ref_raises_not_found(store: CredentialStore):
    with pytest.raises(CredentialNotFound):
        store.get("cred_does_not_exist")


def test_exists_handles_both_failure_modes(
    store: CredentialStore, seeded_tenant: str, pg_client: PostgresClient
):
    assert store.exists("cred_nope") is False

    ref = store.put(
        tenant_id=seeded_tenant,
        scope_json={},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert store.exists(ref) is True

    with pg_client.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE credentials SET expires_at = NOW() - INTERVAL '1 minute' "
                "WHERE credentials_ref = :ref"
            ),
            {"ref": ref},
        )
    assert store.exists(ref) is False


# ---------------------------------------------------------------------------
# Listing / revoke / purge
# ---------------------------------------------------------------------------


def test_list_for_tenant_excludes_expired_by_default(
    store: CredentialStore, seeded_tenant: str, pg_client: PostgresClient
):
    live_ref = store.put(
        tenant_id=seeded_tenant,
        scope_json={"label": "live"},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    stale_ref = store.put(
        tenant_id=seeded_tenant,
        scope_json={"label": "stale"},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    with pg_client.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE credentials SET expires_at = NOW() - INTERVAL '1 minute' "
                "WHERE credentials_ref = :ref"
            ),
            {"ref": stale_ref},
        )

    live_only = store.list_for_tenant(seeded_tenant)
    assert live_ref in {r.credentials_ref for r in live_only}
    assert stale_ref not in {r.credentials_ref for r in live_only}

    all_creds = store.list_for_tenant(seeded_tenant, include_expired=True)
    refs = {r.credentials_ref for r in all_creds}
    assert {live_ref, stale_ref}.issubset(refs)


def test_revoke_removes_row(store: CredentialStore, seeded_tenant: str):
    ref = store.put(
        tenant_id=seeded_tenant,
        scope_json={},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert store.revoke(ref) is True
    with pytest.raises(CredentialNotFound):
        store.get(ref)
    # Idempotent: second revoke is a no-op.
    assert store.revoke(ref) is False


def test_purge_expired(store: CredentialStore, seeded_tenant: str, pg_client: PostgresClient):
    ref_a = store.put(
        tenant_id=seeded_tenant,
        scope_json={"label": "a"},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    ref_b = store.put(
        tenant_id=seeded_tenant,
        scope_json={"label": "b"},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    live_ref = store.put(
        tenant_id=seeded_tenant,
        scope_json={"label": "live"},
        secret_payload=b'"x"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    with pg_client.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE credentials SET expires_at = NOW() - INTERVAL '1 minute' "
                "WHERE credentials_ref IN (:a, :b)"
            ),
            {"a": ref_a, "b": ref_b},
        )
    n = store.purge_expired()
    # >=2 because other tests in this module may have left expired
    # rows behind; the contract is that all expired rows get purged.
    assert n >= 2
    assert not store.exists(ref_a)
    assert not store.exists(ref_b)
    # live ref is still there
    assert store.exists(live_ref) is True
