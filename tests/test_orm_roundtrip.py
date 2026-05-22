"""Integration: create the spine in Postgres and round-trip a full canonical
hierarchy end to end.

Requires \\`make up\\` (docker-compose stack) to be running.

Anchored to DATA_ARCHITECTURE.md \u00a74 (canonical hierarchy) and \u00a75 (schema).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tandemn_system_data.clients import PostgresClient
from tandemn_system_data.db import (
    ALL_TABLES,
    AttemptRow,
    Base,
    ChainRow,
    CredentialsRow,
    DecisionRow,
    EventRow,
    JobRow,
    OutcomeRow,
    PlacementAlternativeRow,
    PlanRow,
    ResourceMapRow,
    TenantRow,
)
from tandemn_system_data.ids import (
    new_attempt_id,
    new_chain_id,
    new_credentials_ref,
    new_decision_id,
    new_event_id,
    new_job_id,
    new_outcome_id,
    new_placement_alternative_id,
    new_plan_id,
    new_resource_map_id,
    new_tenant_id,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_client() -> PostgresClient:
    return PostgresClient()


@pytest.fixture(scope="module", autouse=True)
def _reset_schema(pg_client: PostgresClient):
    """Drop and recreate the spine before this module runs.

    Module-scoped so all tests share one fresh schema. Phase 1b uses
    create_all directly; Alembic migrations land in a separate commit.
    """
    Base.metadata.drop_all(pg_client.engine)
    Base.metadata.create_all(pg_client.engine)
    yield
    # leave the schema in place so a developer can inspect with psql.


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_all_tables_created(pg_client: PostgresClient):
    inspector_tables = set(Base.metadata.tables.keys())
    expected = {row.__tablename__ for row in ALL_TABLES}
    assert expected.issubset(inspector_tables)


def test_full_canonical_hierarchy_roundtrip(pg_client: PostgresClient):
    """Insert tenant \u2192 job \u2192 decision \u2192 plan \u2192 alt \u2192 chain \u2192
    attempt \u2192 outcome \u2192 event \u2192 credentials, then read them back.

    Anchored to DATA_ARCHITECTURE.md \u00a74.
    """
    now = datetime.now(UTC)

    tenant_id = new_tenant_id()
    resource_map_id = new_resource_map_id()
    job_id = new_job_id()
    plan_id = new_plan_id()
    decision_id = new_decision_id()
    alt_id = new_placement_alternative_id()
    chain_id = new_chain_id()
    attempt_id = new_attempt_id()
    outcome_id = new_outcome_id()
    event_id = new_event_id()
    cred_ref = new_credentials_ref()

    with pg_client.begin() as s:
        # Tenant + tenant-scoped rows first.
        s.add(TenantRow(tenant_id=tenant_id, name="Ventura", created_at=now))
        s.flush()
        s.add(
            ResourceMapRow(
                resource_map_id=resource_map_id,
                tenant_id=tenant_id,
                snapshot_json={"nodes": [{"node_id": "gpu-1", "hw": "H100"}]},
                captured_at=now,
            )
        )
        s.add(
            JobRow(
                job_id=job_id,
                tenant_id=tenant_id,
                kind="batch",
                spec_json={"model": "google/gemma-4-31B-it"},
                input_source={"type": "s3", "uri": "s3://ventura/inputs/x.jsonl"},
                output_target={"type": "s3", "uri": "s3://ventura/outputs/"},
                status="submitted",
                created_at=now,
            )
        )
        # Plans first because decisions and placement_alternatives FK to plans.
        s.add(
            PlanRow(
                plan_id=plan_id,
                plan_json={"alternatives": []},
                slo_json={"target_throughput_tps": 1500},
                created_at=now,
            )
        )
        s.flush()
        s.add(
            DecisionRow(
                decision_id=decision_id,
                job_id=job_id,
                plan_id=plan_id,
                koi_version="koi-0.1",
                rationale_json={"why": "demo"},
                created_at=now,
            )
        )
        s.flush()
        s.add(
            PlacementAlternativeRow(
                alternative_id=alt_id,
                plan_id=plan_id,
                rank=0,
                strategy="pd_disaggregated",
                pd_ratio=2.0,
                sizing_json={
                    "prefill": {"shape": {"hw": "H100", "tp": 2, "pp": 4}},
                    "decode": {
                        "shape": {"hw": "A100", "tp": 1, "pp": 1},
                        "target_chains": 3,
                        "estimated_throughput_tps_per_chain": 500,
                    },
                },
                estimated_throughput_tps=1500,
                status="started",
                created_at=now,
            )
        )
        s.flush()
        s.add(
            ChainRow(
                chain_id=chain_id,
                alternative_id=alt_id,
                role="decode",
                shape_json={"hw": "A100", "tp": 1, "pp": 1},
                parallelism_json={"tp": 1, "pp": 1},
                target_node="gpu-1",
                status="running",
                created_at=now,
            )
        )
        s.flush()
        s.add(
            AttemptRow(
                attempt_id=attempt_id,
                chain_id=chain_id,
                status="completed",
                started_at=now,
                ended_at=now + timedelta(seconds=30),
                reason_code=None,
            )
        )
        s.add(
            OutcomeRow(
                outcome_id=outcome_id,
                chain_id=chain_id,
                status="success",
                metrics_json={"realized_tps": 480, "ttft_ms": 215},
                created_at=now + timedelta(seconds=31),
            )
        )
        s.add(
            EventRow(
                event_id=event_id,
                tenant_id=tenant_id,
                job_id=job_id,
                chain_id=chain_id,
                type="outcome.recorded",
                payload_json={
                    "outcome_id": outcome_id,
                    "chain_id": chain_id,
                    "status": "success",
                },
                created_at=now + timedelta(seconds=32),
            )
        )
        s.add(
            CredentialsRow(
                credentials_ref=cred_ref,
                tenant_id=tenant_id,
                scope_json={"prefix": "s3://ventura/inputs/"},
                secret_payload=b"opaque-encrypted-token",
                expires_at=now + timedelta(hours=1),
                created_at=now,
            )
        )

    # ---- Read back through the canonical hierarchy ----
    with pg_client.session() as s:
        j = s.get(JobRow, job_id)
        assert j is not None
        assert j.tenant_id == tenant_id
        assert j.input_source["uri"].startswith("s3://")

        d = s.get(DecisionRow, decision_id)
        assert d is not None and d.job_id == job_id and d.plan_id == plan_id

        alt = s.get(PlacementAlternativeRow, alt_id)
        assert alt is not None
        assert alt.strategy == "pd_disaggregated"
        assert float(alt.pd_ratio) == 2.0
        assert alt.sizing_json["decode"]["target_chains"] == 3

        c = s.get(ChainRow, chain_id)
        assert c is not None
        assert c.role == "decode"
        assert c.shape_json["hw"] == "A100"

        a = s.get(AttemptRow, attempt_id)
        assert a is not None and a.status == "completed"

        o = s.get(OutcomeRow, outcome_id)
        assert o is not None and o.metrics_json["realized_tps"] == 480

        ev = s.get(EventRow, event_id)
        assert ev is not None and ev.type == "outcome.recorded"

        cred = s.get(CredentialsRow, cred_ref)
        assert cred is not None and cred.expires_at > now


def test_pd_ratio_can_be_null_for_aggregate(pg_client: PostgresClient):
    """At the DB layer, pd_ratio is nullable. The Pydantic layer enforces
    the semantic rule (aggregate => NULL). This test just exercises the
    column's storage shape."""
    now = datetime.now(UTC)
    plan_id = new_plan_id()
    alt_id = new_placement_alternative_id()

    with pg_client.begin() as s:
        s.add(PlanRow(plan_id=plan_id, plan_json={}, slo_json={}, created_at=now))
        s.flush()
        s.add(
            PlacementAlternativeRow(
                alternative_id=alt_id,
                plan_id=plan_id,
                rank=0,
                strategy="aggregate",
                pd_ratio=None,
                sizing_json={
                    "aggregate": {
                        "shape": {"hw": "H100", "tp": 8, "pp": 1},
                        "target_chains": 8,
                        "estimated_throughput_tps_per_chain": 200,
                    }
                },
                estimated_throughput_tps=1600,
                status="pending",
                created_at=now,
            )
        )

    with pg_client.session() as s:
        alt = s.get(PlacementAlternativeRow, alt_id)
        assert alt is not None
        assert alt.pd_ratio is None
        assert alt.sizing_json["aggregate"]["target_chains"] == 8
