"""Unit tests for Pydantic canonical models.

Anchors every test to a DATA_ARCHITECTURE.md section so the schema rules
are traceable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tandemn_system_data.models import (
    AlternativeStatus,
    Attempt,
    AttemptStatus,
    Chain,
    ChainRole,
    ChainStatus,
    Credentials,
    Decision,
    Event,
    Job,
    JobKind,
    JobStatus,
    Outcome,
    OutcomeStatus,
    PlacementAlternative,
    PlacementStrategy,
    Plan,
    ResourceMap,
    Tenant,
)

# ---------------------------------------------------------------------------
# Tenant / ResourceMap / Job (DATA_ARCHITECTURE.md §5)
# ---------------------------------------------------------------------------


def test_tenant_defaults():
    t = Tenant(name="Ventura")
    assert t.tenant_id.startswith("tnt_")
    assert t.name == "Ventura"
    assert t.created_at.tzinfo is not None  # tz-aware


def test_resource_map_defaults():
    rm = ResourceMap(tenant_id="tnt_abc", snapshot_json={"nodes": []})
    assert rm.resource_map_id.startswith("rmap_")
    assert rm.snapshot_json == {"nodes": []}


def test_job_defaults_status_submitted():
    j = Job(tenant_id="tnt_abc", kind=JobKind.BATCH)
    assert j.job_id.startswith("job_")
    assert j.status is JobStatus.SUBMITTED
    assert j.input_source == {}
    assert j.output_target == {}
    assert j.completed_at is None


def test_job_input_source_is_pointer_not_data():
    """DATA_ARCHITECTURE.md §5: input_source describes WHERE data lives."""
    j = Job(
        tenant_id="tnt_abc",
        kind=JobKind.BATCH,
        input_source={
            "type": "s3",
            "uri": "s3://customer/inputs.jsonl",
            "format": "jsonl",
            "credentials_ref": "cred_01",
        },
        output_target={
            "type": "s3",
            "uri": "s3://customer/outputs/",
            "format": "jsonl",
            "credentials_ref": "cred_01",
        },
    )
    assert j.input_source["uri"].startswith("s3://")
    assert j.output_target["uri"].endswith("/")


def test_extras_forbidden():
    with pytest.raises(ValidationError):  # pydantic.ValidationError subclass
        Tenant(name="X", bogus_field="nope")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Plan / Decision (DATA_ARCHITECTURE.md §5)
# ---------------------------------------------------------------------------


def test_plan_carries_slo_and_plan_json():
    p = Plan(plan_json={"alternatives": []}, slo_json={"target_throughput_tps": 1500})
    assert p.plan_id.startswith("plan_")
    assert p.slo_json["target_throughput_tps"] == 1500


def test_decision_references_plan_and_job():
    d = Decision(job_id="job_1", plan_id="plan_1", koi_version="koi-0.1")
    assert d.decision_id.startswith("dec_")
    assert d.koi_version == "koi-0.1"


# ---------------------------------------------------------------------------
# PlacementAlternative (DATA_ARCHITECTURE.md §5 notes + §6)
# ---------------------------------------------------------------------------


def test_pd_disaggregated_requires_pd_ratio():
    """§5: pd_ratio NULL for aggregate; required for pd_disaggregated."""
    with pytest.raises(ValidationError):
        PlacementAlternative(
            plan_id="plan_1",
            rank=0,
            strategy=PlacementStrategy.PD_DISAGGREGATED,
            pd_ratio=None,
            sizing_json={"prefill": {}, "decode": {}},
        )


def test_aggregate_must_not_have_pd_ratio():
    with pytest.raises(ValidationError):
        PlacementAlternative(
            plan_id="plan_1",
            rank=0,
            strategy=PlacementStrategy.AGGREGATE,
            pd_ratio=1.0,
            sizing_json={"aggregate": {}},
        )


def test_pd_disaggregated_accepts_positive_ratio():
    alt = PlacementAlternative(
        plan_id="plan_1",
        rank=0,
        strategy=PlacementStrategy.PD_DISAGGREGATED,
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
    )
    assert alt.pd_ratio == 2.0
    assert alt.status is AlternativeStatus.PENDING


def test_aggregate_alternative_ok():
    alt = PlacementAlternative(
        plan_id="plan_1",
        rank=1,
        strategy=PlacementStrategy.AGGREGATE,
        pd_ratio=None,
        sizing_json={
            "aggregate": {
                "shape": {"hw": "H100", "tp": 8, "pp": 1},
                "target_chains": 8,
                "estimated_throughput_tps_per_chain": 200,
            }
        },
        estimated_throughput_tps=1600,
    )
    assert alt.alternative_id.startswith("alt_")


def test_pd_ratio_must_be_positive():
    with pytest.raises(ValidationError):
        PlacementAlternative(
            plan_id="plan_1",
            rank=0,
            strategy=PlacementStrategy.PD_DISAGGREGATED,
            pd_ratio=0,
        )
    with pytest.raises(ValidationError):
        PlacementAlternative(
            plan_id="plan_1",
            rank=0,
            strategy=PlacementStrategy.PD_DISAGGREGATED,
            pd_ratio=-1.0,
        )


def test_rank_must_be_non_negative():
    with pytest.raises(ValidationError):
        PlacementAlternative(
            plan_id="plan_1",
            rank=-1,
            strategy=PlacementStrategy.AGGREGATE,
        )


# ---------------------------------------------------------------------------
# Chain / Attempt / Outcome (DATA_ARCHITECTURE.md §5)
# ---------------------------------------------------------------------------


def test_chain_accepts_all_three_roles():
    """§5: role: prefill | decode | aggregate."""
    for role in (ChainRole.PREFILL, ChainRole.DECODE, ChainRole.AGGREGATE):
        c = Chain(
            alternative_id="alt_1",
            role=role,
            shape_json={"hw": "H100"},
            parallelism_json={"tp": 2, "pp": 4},
        )
        assert c.role is role
        assert c.status is ChainStatus.PENDING


def test_attempt_default_status_started():
    a = Attempt(chain_id="chain_1")
    assert a.attempt_id.startswith("att_")
    assert a.status is AttemptStatus.STARTED
    assert a.started_at.tzinfo is not None
    assert a.ended_at is None


def test_outcome_carries_metrics():
    o = Outcome(
        chain_id="chain_1",
        status=OutcomeStatus.SUCCESS,
        metrics_json={"realized_tps": 480, "ttft_ms": 215},
    )
    assert o.outcome_id.startswith("out_")
    assert o.metrics_json["realized_tps"] == 480


# ---------------------------------------------------------------------------
# Event / Credentials (DATA_ARCHITECTURE.md §5 and §7)
# ---------------------------------------------------------------------------


def test_event_envelope_optional_scope_ids():
    """§5: events may have tenant_id, job_id, chain_id; type and payload required."""
    e = Event(type="job.submitted", payload_json={"job_id": "job_1"})
    assert e.event_id.startswith("evt_")
    assert e.tenant_id is None
    assert e.job_id is None
    assert e.chain_id is None


def test_credentials_require_expiry_and_secret():
    c = Credentials(
        tenant_id="tnt_1",
        scope_json={"prefix": "s3://customer/inputs/"},
        secret_payload=b'"opaque-encrypted-token"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert c.credentials_ref.startswith("cred_")
    assert c.secret_payload == b'"opaque-encrypted-token"'
    assert c.expires_at > datetime.now(UTC)
