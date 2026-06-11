"""Integration test: full canonical hierarchy through the Alembic
migration path and back.

Requires Postgres (`make up`).
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tandemn_system_data.clients import PostgresClient
from tandemn_system_data.db import (
    ALL_TABLES,
    Base,
    ChainRow,
    CredentialsRow,
    EventRow,
    JobRow,
    PlanRow,
    UserRow,
)
from tandemn_system_data.ids import (
    new_chain_id,
    new_credentials_ref,
    new_event_id,
    new_job_id,
    new_koi_tick_id,
    new_plan_id,
    new_user_id,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def pg_client() -> PostgresClient:
    return PostgresClient()


@pytest.fixture(scope="module", autouse=True)
def _reset_schema(pg_client: PostgresClient):
    """Drop the spine and reapply the Alembic baseline before this module runs.

    We go through Alembic rather than create_all so the test exercises the
    same migration path production will use.
    """
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
    # Leave the schema in place so a developer can inspect with psql.


def test_all_tables_created(pg_client: PostgresClient):
    inspector_tables = set(Base.metadata.tables.keys())
    expected = {row.__tablename__ for row in ALL_TABLES}
    assert expected.issubset(inspector_tables)


def test_full_canonical_hierarchy_roundtrip(pg_client: PostgresClient):
    """Insert user → job → plan → chains → event → credentials, then
    read them back. Anchored to DATA_ARCHITECTURE.md §4."""
    now = datetime.now(UTC)

    user_id = new_user_id()
    job_id = new_job_id()
    tick_id = new_koi_tick_id()  # correlation only; no koi_ticks table
    plan_id = new_plan_id()
    prefill_chain_id = new_chain_id()
    decode_chain_id = new_chain_id()
    event_id = new_event_id()
    cred_ref = new_credentials_ref()

    with pg_client.begin() as s:
        s.add(UserRow(user_id=user_id, name="Ventura", created_at=now))
        s.flush()
        s.add(
            JobRow(
                job_id=job_id,
                user_id=user_id,
                kind="batch",
                spec_json={"model": "google/gemma-4-31B-it"},
                input_source={"type": "s3", "uri": "s3://ventura/inputs/x.jsonl"},
                output_target={"type": "s3", "uri": "s3://ventura/outputs/"},
                status="waiting",
                created_at=now,
            )
        )
        s.flush()
        s.add(
            PlanRow(
                plan_id=plan_id,
                user_id=user_id,
                koi_version="koi-0.1",
                tick_rationale="spare H100 capacity; gang-place the PD pair",
                actions_json=[
                    {
                        "job_id": job_id,
                        "type": "place",
                        "ladder": [
                            {"prefill": {"gpu": "H100", "count": 8, "chains": 2}},
                            {"decode": {"gpu": "A100", "count": 8, "chains": 1}},
                        ],
                        "target_tps": 1500,
                    }
                ],
                status="applied",
                created_at=now,
            )
        )
        # Gang scheduling: prefill + decode chains launch together,
        # both job-scoped, with plan provenance.
        s.add(
            ChainRow(
                chain_id=prefill_chain_id,
                job_id=job_id,
                plan_id=plan_id,
                role="prefill",
                shape_json={"gpu": "H100", "count": 8, "tp": 2, "pp": 4},
                target_node="gpu-node-1",
                status="running",
                created_at=now,
            )
        )
        s.add(
            ChainRow(
                chain_id=decode_chain_id,
                job_id=job_id,
                plan_id=plan_id,
                role="decode",
                shape_json={"gpu": "A100", "count": 8, "tp": 1, "pp": 1},
                target_node="gpu-node-2",
                status="running",
                created_at=now,
            )
        )
        s.add(
            EventRow(
                event_id=event_id,
                user_id=user_id,
                job_id=job_id,
                chain_id=decode_chain_id,
                type="chain.launched",
                payload_json={"chain_id": decode_chain_id, "job_id": job_id, "role": "decode"},
                created_at=now,
            )
        )
        s.add(
            CredentialsRow(
                credentials_ref=cred_ref,
                user_id=user_id,
                scope_json={"prefix": "s3://ventura/inputs/"},
                secret_payload=b'"opaque-encrypted-token"',
                expires_at=now + timedelta(hours=1),
                created_at=now,
            )
        )

    # ---- Read back through the canonical hierarchy ----
    with pg_client.session() as s:
        j = s.get(JobRow, job_id)
        assert j is not None
        assert j.user_id == user_id
        assert j.status == "waiting"
        assert j.finish_reason is None
        assert j.input_source["uri"].startswith("s3://")

        p = s.get(PlanRow, plan_id)
        assert p is not None and p.user_id == user_id
        assert p.actions_json[0]["type"] == "place"
        assert p.actions_json[0]["ladder"][0]["prefill"]["count"] == 8
        assert tick_id  # correlation string exists; no table to join

        pf = s.get(ChainRow, prefill_chain_id)
        dc = s.get(ChainRow, decode_chain_id)
        assert pf.job_id == dc.job_id == job_id
        assert pf.plan_id == dc.plan_id == plan_id
        assert {pf.role, dc.role} == {"prefill", "decode"}
        assert dc.shape_json["gpu"] == "A100"

        ev = s.get(EventRow, event_id)
        assert ev is not None and ev.type == "chain.launched"

        cred = s.get(CredentialsRow, cred_ref)
        assert cred is not None and cred.expires_at > now


def test_job_cascade_deletes_chains_but_not_events(pg_client: PostgresClient):
    """chains FK CASCADE from jobs; events survive (audit log, no FK)."""
    now = datetime.now(UTC)
    user_id, job_id, chain_id, event_id = (
        new_user_id(),
        new_job_id(),
        new_chain_id(),
        new_event_id(),
    )

    with pg_client.begin() as s:
        s.add(UserRow(user_id=user_id, name="cascade", created_at=now))
        s.flush()
        s.add(
            JobRow(
                job_id=job_id,
                user_id=user_id,
                kind="batch",
                spec_json={},
                input_source={},
                output_target={},
                status="running",
                created_at=now,
            )
        )
        s.flush()
        s.add(
            ChainRow(
                chain_id=chain_id,
                job_id=job_id,
                role="aggregate",
                shape_json={},
                status="running",
                created_at=now,
            )
        )
        s.add(
            EventRow(
                event_id=event_id,
                user_id=user_id,
                job_id=job_id,
                chain_id=chain_id,
                type="chain.launched",
                payload_json={},
                created_at=now,
            )
        )

    with pg_client.begin() as s:
        s.delete(s.get(JobRow, job_id))

    with pg_client.session() as s:
        assert s.get(ChainRow, chain_id) is None  # cascaded
        assert s.get(EventRow, event_id) is not None  # audit log survives
