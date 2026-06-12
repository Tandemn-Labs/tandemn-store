"""Unit tests for the system_data contracts: IDs, models, events,
resource map. No infrastructure required."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tandemn_system_data import events, ids
from tandemn_system_data.clients import (
    ResourceMapClient,
    ResourceMapStore,
    create_resource_map_app,
)
from tandemn_system_data.models import (
    ActionType,
    Chain,
    ChainRole,
    ChainStatus,
    Credentials,
    Job,
    JobKind,
    JobStatus,
    Plan,
    PlanAction,
    ResourceMap,
    ResourcePool,
    User,
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


# ----- Resource map (in-memory contract, not a table) ------------------------


def _pools(available: int) -> dict[str, dict[str, ResourcePool]]:
    return {"aws": {"g6e.12xlarge": ResourcePool(total=8, available=available)}}


def test_resource_map_store_versions_never_collide():
    store = ResourceMapStore()
    assert store.get().version == 0

    threads = [
        threading.Thread(target=lambda: [store.replace(_pools(1)) for _ in range(50)])
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.get().version == 400


def test_resource_map_endpoint_and_client_round_trip(monkeypatch):
    store = ResourceMapStore()
    store.replace(_pools(available=3))
    app_client = TestClient(create_resource_map_app(store))

    resp = app_client.get("/resource-map")
    assert ResourceMap.model_validate(resp.json()).pools["aws"]["g6e.12xlarge"].available == 3

    import tandemn_system_data.clients.resource_map as rm_module

    monkeypatch.setattr(
        rm_module.httpx, "get", lambda url, timeout=None: app_client.get("/resource-map")
    )
    assert ResourceMapClient("http://orca").get().version == 1

    monkeypatch.setattr(
        rm_module.httpx, "get", lambda url, timeout=None: httpx.Response(500, text="boom")
    )
    with pytest.raises(RuntimeError):
        ResourceMapClient("http://orca").get()
