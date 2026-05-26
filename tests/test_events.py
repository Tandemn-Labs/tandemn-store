"""Tests for the event envelope + typed payload registry.

Anchors every assertion to DATA_ARCHITECTURE.md §9.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tandemn_system_data.events import (
    ALL_EVENT_TYPES,
    PAYLOAD_REGISTRY,
    ChainAttemptStartedPayload,
    JobSubmittedPayload,
    PlacementAlternativeEventPayload,
    payload_model_for,
    validate_payload,
)
from tandemn_system_data.models import AlternativeStatus, ChainRole, Event

# The exact 14 event types listed in DATA_ARCHITECTURE.md §9.
# If §9 changes, this list MUST change in lockstep.
_DOC_EVENT_TYPES = {
    "job.submitted",
    "job.completed",
    "job.failed",
    "plan.requested",
    "plan.returned",
    "placement.alternative_started",
    "placement.alternative_full",
    "placement.alternative_partial",
    "placement.alternative_abandoned",
    "placement.exhausted",
    "job_group.assembled",
    "chain.attempt_started",
    "chain.failed",
    "chain.completed",
    "ratio.violated",
    "outcome.recorded",
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
        "chain.attempt_started",
        {
            "chain_id": "chain_1",
            "attempt_id": "att_1",
            "alternative_id": "alt_1",
            "role": "decode",
            "target_node": "gpu-3",
        },
    )
    assert isinstance(payload, ChainAttemptStartedPayload)
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


def test_placement_alternative_events_share_one_payload_shape():
    """§9: alternative_started/full/partial/abandoned all share the same envelope."""
    common = {
        "job_id": "job_1",
        "decision_id": "dec_1",
        "alternative_id": "alt_1",
        "rank": 0,
        "status": AlternativeStatus.STARTED,
    }
    for event_type in (
        "placement.alternative_started",
        "placement.alternative_full",
        "placement.alternative_partial",
        "placement.alternative_abandoned",
    ):
        payload = validate_payload(event_type, common)
        assert isinstance(payload, PlacementAlternativeEventPayload)


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
