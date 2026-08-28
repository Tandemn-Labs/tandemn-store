"""Unit tests for the system_data contracts: IDs, models, events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tandemn_system_data import events, ids
from tandemn_system_data.models import (
    DEFAULT_MIN_CHAIN_WARMUP_MINUTES,
    ActionType,
    Credentials,
    EvidenceRow,
    Job,
    JobKind,
    JobStatus,
    ModelCatalog,
    Plan,
    PlanAction,
    Rank,
    RankRole,
    RankStatus,
    User,
    evidence_payload_from_row,
    evidence_row_to_payload,
    format_evidence_row_id,
    model_catalog_from_row,
    model_catalog_to_json,
)

# ----- IDs -------------------------------------------------------------------


def test_ids_are_prefixed_unique_and_time_ordered():
    for value, prefix in [
        (ids.new_user_id(), "usr_"),
        (ids.new_job_id(), "job_"),
        (ids.new_plan_id(), "plan_"),
        (ids.new_rank_id(), "rank_"),
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
    assert j.finish_reason is None and j.error_message is None and j.finished_at is None
    assert {s.value for s in JobStatus} == {"waiting", "running", "paused", "finished"}


def test_plan_is_rationale_plus_actions_and_round_trips_json():
    plan = Plan(
        user_id="usr_1",
        tick_rationale="spare H100 capacity; place job B",
        actions=[
            PlanAction(
                job_id="job_b",
                type=ActionType.PLACE,
                ladder=[{"prefill": {"gpu": "H100", "count": 8, "n_replicas": 2}}],
                target_tps=1500,
                target_p99_ttft_ms=500,
                target_p99_tpot_ms=50,
            ),
            PlanAction(job_id="job_d", type=ActionType.DEFER),
            PlanAction(job_id="job_e", type=ActionType.PREEMPT),
        ],
    )
    assert {a.value for a in ActionType} == {"place", "keep", "defer", "preempt", "swap"}
    # actions_json is JSONB in Postgres; the typed list must survive.
    assert Plan.model_validate_json(plan.model_dump_json()) == plan
    assert plan.actions[0].target_p99_ttft_ms == 500
    assert plan.actions[0].target_p99_tpot_ms == 50
    with pytest.raises(ValidationError):
        PlanAction(job_id="job_a", type="explode")  # type: ignore[arg-type]


def test_rank_is_job_scoped_with_optional_plan_provenance():
    rank = Rank(
        job_id="job_1",
        role=RankRole.DECODE,
        shape_json={"gpu": "A100", "count": 8},
        n_replicas=2,
    )
    assert rank.status is RankStatus.LAUNCHING
    assert rank.plan_id is None


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
        X={"gpu_count": 8, "tps": 1200.0},
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
        V_observed_trajectory={"v": [1.0, 2.0]},
        V_predicted_trajectory={"v": [1.1, 2.1]},
        y_observed_trajectory={"y": [0.5]},
        y_predicted={"y": 0.4},
        y_observed_mean={"y": 0.5},
        residuals_per_v={"v": [0.0, 0.0]},
        residuals_per_y={"y": [0.1]},
        cusum_per_mechanism={"m1": (1, 2)},
        deployment_id="deploy-1",
        evidence_available_timestamp_utc=2.0,
        prediction_lineage={
            "schema_version": 3,
            "composite_version": "koi-surrogate-v3:test",
        },
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
    assert back.deployment_id == "deploy-1"
    assert back.evidence_available_timestamp_utc == 2.0
    assert back.prediction_lineage == row.prediction_lineage


def test_models_forbid_extras():
    with pytest.raises(ValidationError):
        User(name="X", bogus="nope")  # type: ignore[call-arg]


def test_model_catalog_defaults_and_json_round_trip():
    catalog = ModelCatalog(
        model_id="Qwen/Qwen3-0.6B",
        num_hidden_layers=28,
        is_moe=False,
        chunked_prefill_enable=True,
    )
    assert catalog.gpu_mem_util == 0.85
    assert catalog.min_chain_warmup_time == DEFAULT_MIN_CHAIN_WARMUP_MINUTES
    assert catalog.max_num_seq == []
    assert catalog.activation_quantization_method == "none"
    assert catalog.weight_quantization_method == "none"
    assert catalog.draft_model_id == ""
    assert catalog.spec_decoding_method == "none"
    assert catalog.num_speculative_tokens == 0
    assert catalog.spec_acceptance_threshold == 0.0

    catalog.max_num_seq = [{"gpu_type": "L4", "value": 64}]
    catalog.min_chain_warmup_time = 15.0
    body = model_catalog_to_json(catalog)
    assert "model_id" not in body and "updated_at" not in body

    back = model_catalog_from_row(
        model_id=catalog.model_id, updated_at=catalog.updated_at, catalog=body
    )
    assert back.num_hidden_layers == 28
    assert back.chunked_prefill_enable is True
    assert back.max_num_seq == [{"gpu_type": "L4", "value": 64}]
    assert back.min_chain_warmup_time == 15.0


def test_model_catalog_forbids_extras():
    with pytest.raises(ValidationError):
        ModelCatalog(model_id="m", bogus="nope")  # type: ignore[call-arg]


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
        "job.place",
        "job.submitted",
        "job.placed",
        "job.paused",
        "job.resumed",
        "job.finished",
        "tick.started",
        "tick.completed",
        "plan.created",
        "plan.applied",
        "rank.launching",
        "rank.launched",
        "rank.running",
        "rank.stopped",
        "rank.failed",
    }
    assert set(events.ALL_EVENT_TYPES) == set(events.PAYLOAD_REGISTRY)


def test_payload_validation_enforces_shape():
    placing = events.validate_payload(
        "job.place",
        {
            "job_id": "job_1",
            "user_id": "usr_1",
            "plan_id": "plan_1",
            "action_type": "place",
        },
    )
    assert placing.plan_id == "plan_1"  # type: ignore[attr-defined]
    assert placing.user_id == "usr_1"  # type: ignore[attr-defined]

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
