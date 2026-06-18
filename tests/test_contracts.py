"""Unit tests for the system_data contracts: IDs, models, events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tandemn_system_data import events, ids
from tandemn_system_data.models import (
    ActionType,
    Chain,
    ChainRole,
    ChainStatus,
    Credentials,
    EvidenceRow,
    Job,
    JobKind,
    JobStatus,
    Plan,
    PlanAction,
    User,
    evidence_payload_from_row,
    evidence_row_to_payload,
    format_evidence_row_id,
)

# ----- IDs -------------------------------------------------------------------


def test_ids_are_prefixed_unique_and_time_ordered():
    for value, prefix in [
        (ids.new_user_id(), "usr_"),
        (ids.new_job_id(), "job_"),
        (ids.new_plan_id(), "plan_"),
        (ids.new_chain_id(), "chain_"),
        (ids.new_koi_tick_id(), "tick_"),
        (ids.new_event_id(), "evt_"),
        (ids.new_credentials_ref(), "cred_"),
    ]:
        assert value.startswith(prefix)
        assert ids.kind_of(value) in ids.PREFIXES

    batch = [ids.new_job_id() for _ in range(200)]
    assert len(set(batch)) == 200
    assert batch == sorted(batch)  # ULIDs sort by creation time


# ----- Models ----------------------------------------------------------------


def test_job_lifecycle_contract():
    """New jobs start WAITING; statuses are exactly the four MVP states."""
    j = Job(user_id="usr_1", kind=JobKind.BATCH)
    assert j.status is JobStatus.WAITING
    assert j.finish_reason is None and j.finished_at is None
    assert {s.value for s in JobStatus} == {"waiting", "running", "paused", "finished"}


def test_plan_is_rationale_plus_actions_and_round_trips_json():
    plan = Plan(
        user_id="usr_1",
        tick_rationale="spare H100 capacity; place job B",
        actions=[
            PlanAction(
                job_id="job_b",
                type=ActionType.PLACE,
                ladder=[{"prefill": {"gpu": "H100", "count": 8, "chains": 2}}],
                target_tps=1500,
            ),
            PlanAction(job_id="job_d", type=ActionType.DEFER),
            PlanAction(job_id="job_e", type=ActionType.PREEMPT),
        ],
    )
    assert {a.value for a in ActionType} == {"place", "keep", "defer", "preempt", "swap"}
    # actions_json is JSONB in Postgres; the typed list must survive.
    assert Plan.model_validate_json(plan.model_dump_json()) == plan
    with pytest.raises(ValidationError):
        PlanAction(job_id="job_a", type="explode")  # type: ignore[arg-type]


def test_chain_is_job_scoped_with_optional_plan_provenance():
    c = Chain(job_id="job_1", role=ChainRole.DECODE, shape_json={"gpu": "A100", "count": 8})
    assert c.status is ChainStatus.LAUNCHING
    assert c.plan_id is None


def test_evidence_row_id_format():
    row_id = format_evidence_row_id(42, "job_abc", "prefill-0")
    assert row_id == "42_job_abc_prefill-0"
    row = EvidenceRow(
        row_id=row_id,
        tick=42,
        deploy_timestamp_utc=1_700_000_000.0,
        job_id="job_abc",
        rank_id="prefill-0",
        env_label=("reserved", "aws", "us-east-1", "use1-az1", "H100"),
        X={"gpu_count": 8},
        W_observed={"tps": 1200.0},
        V_observed_trajectory={"latency": [1.0, 2.0]},
        V_predicted_trajectory={"latency": [1.1, 2.1]},
        y_observed_trajectory={"cost": [0.5]},
        y_predicted={"cost": 0.48},
        y_observed_mean={"cost": 0.5},
        residuals_per_v={"latency": [0.0, 0.0]},
        residuals_per_y={"cost": [0.02]},
    )
    assert row.row_id == row_id and row.theory_blob is None


def test_evidence_row_payload_round_trip():
    row = EvidenceRow(
        row_id="1_job_a_prefill",
        tick=1,
        deploy_timestamp_utc=1.0,
        job_id="job_a",
        rank_id="prefill",
        env_label=("spot", "aws", "us-east-1", "use1-az1", "H100"),
        X={"k": 1},
        W_observed={"tps": 100.0},
        V_observed_trajectory={"v": [1.0, 2.0]},
        V_predicted_trajectory={"v": [1.1, 2.1]},
        y_observed_trajectory={"y": [0.5]},
        y_predicted={"y": 0.4},
        y_observed_mean={"y": 0.5},
        residuals_per_v={"v": [0.0, 0.0]},
        residuals_per_y={"y": [0.1]},
        cusum_per_mechanism={"m1": (1, 2)},
    )
    payload = evidence_row_to_payload(row)
    back = evidence_payload_from_row(
        row_id=row.row_id,
        tick=row.tick,
        deploy_timestamp_utc=row.deploy_timestamp_utc,
        job_id=row.job_id,
        rank_id=row.rank_id,
        payload=payload,
    )
    assert back.env_label == row.env_label
    assert back.cusum_per_mechanism == {"m1": (1, 2)}
    assert back.y_predicted == row.y_predicted


def test_models_forbid_extras():
    with pytest.raises(ValidationError):
        User(name="X", bogus="nope")  # type: ignore[call-arg]


def test_credentials_require_expiry_and_secret():
    c = Credentials(
        user_id="usr_1",
        scope_json={"prefix": "s3://customer/inputs/"},
        secret_payload=b'"opaque"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert c.credentials_ref.startswith("cred_")


# ----- Events ----------------------------------------------------------------


def test_event_registry_matches_doc_catalog():
    """DATA_ARCHITECTURE.md §9 and the registry must change in lockstep."""
    assert set(events.PAYLOAD_REGISTRY) == {
        "job.submitted",
        "job.placed",
        "job.paused",
        "job.resumed",
        "job.finished",
        "tick.started",
        "tick.completed",
        "plan.created",
        "plan.applied",
        "chain.launched",
        "chain.running",
        "chain.stopped",
        "chain.failed",
    }
    assert set(events.ALL_EVENT_TYPES) == set(events.PAYLOAD_REGISTRY)


def test_payload_validation_enforces_shape():
    ok = events.validate_payload(
        "job.finished", {"job_id": "job_1", "user_id": "usr_1", "finish_reason": "FAILED"}
    )
    assert ok.finish_reason == "FAILED"  # type: ignore[attr-defined]

    with pytest.raises(ValidationError):
        events.validate_payload("job.submitted", {"user_id": "usr_1"})  # missing job_id
    with pytest.raises(ValidationError):
        events.validate_payload("job.submitted", {"job_id": "j", "user_id": "u", "extra": "boom"})
    with pytest.raises(ValueError):
        events.payload_model_for("not.a.real.event")
