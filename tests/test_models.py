"""Unit tests for Pydantic canonical models.

Anchors every test to a DATA_ARCHITECTURE.md section so the schema rules
are traceable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tandemn_system_data.models import (
    ActionType,
    Chain,
    ChainRole,
    ChainStatus,
    Credentials,
    Event,
    Job,
    JobKind,
    JobStatus,
    Plan,
    PlanAction,
    ResourceMap,
    ResourcePool,
    User,
)

# ---------------------------------------------------------------------------
# User / ResourceMap / Job (DATA_ARCHITECTURE.md §5)
# ---------------------------------------------------------------------------


def test_user_defaults():
    t = User(name="Ventura")
    assert t.user_id.startswith("usr_")
    assert t.name == "Ventura"
    assert t.created_at.tzinfo is not None  # tz-aware


def test_resource_map_wire_contract():
    """ResourceMap is Orca's in-memory view, NOT a Postgres row: no ID,
    no user FK, just version + pools."""
    rm = ResourceMap(
        version=3,
        pools={"aws": {"g6e.12xlarge": ResourcePool(total=8, available=3)}},
    )
    assert rm.version == 3
    assert rm.pools["aws"]["g6e.12xlarge"].available == 3
    assert rm.updated_at.tzinfo is not None
    # Round-trips through JSON for the GET /resource-map endpoint.
    assert ResourceMap.model_validate_json(rm.model_dump_json()) == rm


def test_job_starts_waiting():
    """New jobs are WAITING until a plan action places them."""
    j = Job(user_id="usr_abc", kind=JobKind.BATCH)
    assert j.job_id.startswith("job_")
    assert j.status is JobStatus.WAITING
    assert j.finish_reason is None
    assert j.finished_at is None


def test_job_status_is_exactly_four_states():
    assert {s.value for s in JobStatus} == {"waiting", "running", "paused", "finished"}


def test_job_input_source_is_pointer_not_data():
    """DATA_ARCHITECTURE.md §5: input_source describes WHERE data lives."""
    j = Job(
        user_id="usr_abc",
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
    with pytest.raises(ValidationError):
        User(name="X", bogus_field="nope")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Plan + actions (DATA_ARCHITECTURE.md §5/§6)
# ---------------------------------------------------------------------------


def test_plan_carries_rationale_and_actions():
    plan = Plan(
        user_id="usr_1",
        koi_version="koi-0.1",
        tick_rationale="cluster has spare H100 capacity; place job B",
        actions=[
            PlanAction(
                job_id="job_b",
                type=ActionType.PLACE,
                ladder=[
                    {"prefill": {"gpu": "H100", "count": 8, "chains": 2}},
                    {"decode": {"gpu": "A100", "count": 8, "chains": 1}},
                ],
                target_tps=1500,
            ),
            PlanAction(job_id="job_c", type=ActionType.KEEP),
            PlanAction(job_id="job_d", type=ActionType.DEFER),
            PlanAction(job_id="job_e", type=ActionType.PREEMPT),
            PlanAction(job_id="job_f", type=ActionType.SWAP, ladder=[{"gpu": "A100"}]),
        ],
    )
    assert plan.plan_id.startswith("plan_")
    assert plan.status == "created"
    assert plan.actions[0].type is ActionType.PLACE
    assert plan.actions[0].ladder[0]["prefill"]["count"] == 8
    assert plan.actions[1].ladder is None  # keep needs no ladder


def test_plan_actions_round_trip_through_json():
    """actions_json is JSONB in Postgres; the typed list must survive."""
    plan = Plan(
        user_id="usr_1",
        actions=[PlanAction(job_id="job_a", type=ActionType.PLACE, ladder=[{"gpu": "H100"}])],
    )
    restored = Plan.model_validate_json(plan.model_dump_json())
    assert restored == plan


def test_plan_action_rejects_unknown_type():
    with pytest.raises(ValidationError):
        PlanAction(job_id="job_a", type="explode")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Chain (DATA_ARCHITECTURE.md §5)
# ---------------------------------------------------------------------------


def test_chain_belongs_to_job_and_accepts_all_roles():
    """Chains are job-scoped; role: prefill | decode | aggregate."""
    for role in (ChainRole.PREFILL, ChainRole.DECODE, ChainRole.AGGREGATE):
        c = Chain(
            job_id="job_1",
            plan_id="plan_1",
            role=role,
            shape_json={"gpu": "H100", "count": 8, "tp": 2, "pp": 4},
        )
        assert c.role is role
        assert c.status is ChainStatus.LAUNCHING


def test_chain_plan_id_is_optional_provenance():
    c = Chain(job_id="job_1", role=ChainRole.AGGREGATE)
    assert c.plan_id is None


# ---------------------------------------------------------------------------
# Event / Credentials (DATA_ARCHITECTURE.md §5 and §7)
# ---------------------------------------------------------------------------


def test_event_envelope_optional_scope_ids():
    """§5: events may have user_id, job_id, chain_id; type and payload required."""
    e = Event(type="job.submitted", payload_json={"job_id": "job_1"})
    assert e.event_id.startswith("evt_")
    assert e.user_id is None
    assert e.job_id is None
    assert e.chain_id is None


def test_credentials_require_expiry_and_secret():
    c = Credentials(
        user_id="usr_1",
        scope_json={"prefix": "s3://customer/inputs/"},
        secret_payload=b'"opaque-encrypted-token"',
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert c.credentials_ref.startswith("cred_")
    assert c.secret_payload == b'"opaque-encrypted-token"'
    assert c.expires_at > datetime.now(UTC)
