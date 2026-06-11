"""Tests for the event envelope + typed payload registry.

Anchors every assertion to DATA_ARCHITECTURE.md §9.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tandemn_system_data.events import (
    ALL_EVENT_TYPES,
    PAYLOAD_REGISTRY,
    ChainLaunchedPayload,
    JobFinishedPayload,
    JobSubmittedPayload,
    PlanCreatedPayload,
    payload_model_for,
    validate_payload,
)
from tandemn_system_data.models import ActionType, ChainRole, Event

# The exact event types listed in DATA_ARCHITECTURE.md §9.
# If §9 changes, this list MUST change in lockstep.
_DOC_EVENT_TYPES = {
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


def test_registry_matches_doc_section_9():
    """Every event type from DATA_ARCHITECTURE.md §9 has a registered payload."""
    assert set(PAYLOAD_REGISTRY) == _DOC_EVENT_TYPES
    assert set(ALL_EVENT_TYPES) == _DOC_EVENT_TYPES


def test_payload_model_for_known_type():
    model = payload_model_for("job.submitted")
    assert model is JobSubmittedPayload


def test_payload_model_for_rejects_unknown_type():
    with pytest.raises(ValueError):
        payload_model_for("totally.not.a.real.event")


def test_validate_payload_accepts_correct_shape():
    payload = validate_payload(
        "chain.launched",
        {
            "chain_id": "chain_1",
            "job_id": "job_1",
            "plan_id": "plan_1",
            "role": "decode",
            "shape_json": {"gpu": "A100", "count": 8},
            "target_node": "gpu-3",
        },
    )
    assert isinstance(payload, ChainLaunchedPayload)
    assert payload.role is ChainRole.DECODE


def test_validate_payload_rejects_missing_required_field():
    with pytest.raises(ValidationError):
        validate_payload("job.submitted", {"user_id": "usr_1"})  # missing job_id


def test_validate_payload_rejects_extras():
    """All payloads forbid extras."""
    with pytest.raises(ValidationError):
        validate_payload(
            "job.submitted",
            {"job_id": "job_1", "user_id": "usr_1", "unexpected": "boom"},
        )


def test_job_finished_distinguishes_success_from_failure():
    ok = JobFinishedPayload(job_id="job_1", user_id="usr_1")
    failed = JobFinishedPayload(job_id="job_2", user_id="usr_1", finish_reason="FAILED")
    assert ok.finish_reason is None
    assert failed.finish_reason == "FAILED"


def test_plan_created_mirrors_actions():
    payload = validate_payload(
        "plan.created",
        {
            "plan_id": "plan_1",
            "user_id": "usr_1",
            "tick_id": "tick_01ABC",
            "actions": {"job_a": "place", "job_b": "defer", "job_c": "preempt"},
        },
    )
    assert isinstance(payload, PlanCreatedPayload)
    assert payload.actions["job_a"] is ActionType.PLACE


def test_event_envelope_carries_typed_payload_as_dict():
    """The Event row stores payload_json as a dict; the typed model
    is the contract for producers/consumers, but the row is JSONB."""
    payload = JobSubmittedPayload(job_id="job_1", user_id="usr_1")
    e = Event(
        user_id="usr_1",
        job_id="job_1",
        type="job.submitted",
        payload_json=payload.model_dump(),
    )
    assert e.type == "job.submitted"
    assert e.payload_json == {"job_id": "job_1", "user_id": "usr_1"}
    # Round-trip the typed validation off the envelope.
    parsed = validate_payload(e.type, e.payload_json)
    assert isinstance(parsed, JobSubmittedPayload)


def test_all_payload_models_forbid_extras():
    """Defensive: every model in the registry must reject unknown fields."""
    for event_type, model in PAYLOAD_REGISTRY.items():
        assert model.model_config.get("extra") == "forbid", (
            f"{event_type} -> {model.__name__} must forbid extras"
        )
