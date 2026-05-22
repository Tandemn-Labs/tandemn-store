"""Event envelope + typed payload registry (DATA_ARCHITECTURE.md §9).

Every event Tandemn emits has the same envelope (see models.Event):

    { event_id, tenant_id?, job_id?, chain_id?, type, payload_json, created_at }

This module defines:
  - EventType: a Literal enum of the 14 canonical event types from §9.
  - Typed payload models per event type.
  - A registry mapping type -> payload model so consumers can validate
    incoming events.

Event types are stable wire strings; never rename without a migration
of the events table.

Per §8: events are an AP delivery channel (Redis Streams) plus a CP
audit log (Postgres `events` table). Writers persist to Postgres FIRST,
then XADD to Redis. Consumers are idempotent on `event_id`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from tandemn_system_data.models._base import CanonicalModel
from tandemn_system_data.models.enums import (
    AlternativeStatus,
    ChainRole,
    JobStatus,
    OutcomeStatus,
)

# ---------------------------------------------------------------------------
# Event type registry (DATA_ARCHITECTURE.md §9)
# ---------------------------------------------------------------------------


EventType = Literal[
    # Job lifecycle
    "job.submitted",
    "job.completed",
    "job.failed",
    # Planning
    "plan.requested",
    "plan.returned",
    # Placement traversal (§6)
    "placement.alternative_started",
    "placement.alternative_full",
    "placement.alternative_partial",
    "placement.alternative_abandoned",
    "placement.exhausted",
    "job_group.assembled",
    # Chain lifecycle
    "chain.attempt_started",
    "chain.failed",
    "chain.completed",
    # Ratio enforcement (§6)
    "ratio.violated",
    # Outcome bookkeeping
    "outcome.recorded",
]


ALL_EVENT_TYPES: tuple[str, ...] = (
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
)


# ---------------------------------------------------------------------------
# Payload models
# ---------------------------------------------------------------------------


class _PayloadBase(CanonicalModel):
    """All payloads forbid extras so the wire format stays tight."""


# --- Job lifecycle ---------------------------------------------------------


class JobSubmittedPayload(_PayloadBase):
    job_id: str
    tenant_id: str


class JobCompletedPayload(_PayloadBase):
    job_id: str
    tenant_id: str
    final_status: JobStatus = JobStatus.COMPLETED


class JobFailedPayload(_PayloadBase):
    job_id: str
    tenant_id: str
    reason_code: str
    detail: str | None = None


# --- Planning --------------------------------------------------------------


class PlanRequestedPayload(_PayloadBase):
    job_id: str
    tenant_id: str


class PlanReturnedPayload(_PayloadBase):
    job_id: str
    decision_id: str
    plan_id: str


# --- Placement traversal (§6) ---------------------------------------------


class PlacementAlternativeEventPayload(_PayloadBase):
    """Common payload for placement.alternative_{started,full,partial,abandoned}."""

    job_id: str
    plan_id: str
    alternative_id: str
    rank: int
    status: AlternativeStatus


class PlacementExhaustedPayload(_PayloadBase):
    job_id: str
    plan_id: str
    achieved_throughput_tps: float
    target_throughput_tps: float


class JobGroupAssembledPayload(_PayloadBase):
    job_id: str
    plan_id: str
    achieved_throughput_tps: float
    target_throughput_tps: float
    chain_ids: list[str]


# --- Chain lifecycle -------------------------------------------------------


class ChainAttemptStartedPayload(_PayloadBase):
    chain_id: str
    attempt_id: str
    alternative_id: str
    role: ChainRole
    target_node: str | None = None


class ChainFailedPayload(_PayloadBase):
    chain_id: str
    attempt_id: str | None = None
    reason_code: str
    detail: str | None = None


class ChainCompletedPayload(_PayloadBase):
    chain_id: str
    attempt_id: str | None = None
    metrics_json: dict[str, Any] = Field(default_factory=dict)


# --- Ratio enforcement (§6) -----------------------------------------------


class RatioViolatedPayload(_PayloadBase):
    alternative_id: str
    expected_pd_ratio: float
    realized_pd_ratio: float
    realized_prefill_chains: int
    realized_decode_chains: int


# --- Outcomes --------------------------------------------------------------


class OutcomeRecordedPayload(_PayloadBase):
    outcome_id: str
    chain_id: str
    status: OutcomeStatus
    reason_code: str | None = None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


PAYLOAD_REGISTRY: dict[str, type[_PayloadBase]] = {
    # Job lifecycle
    "job.submitted": JobSubmittedPayload,
    "job.completed": JobCompletedPayload,
    "job.failed": JobFailedPayload,
    # Planning
    "plan.requested": PlanRequestedPayload,
    "plan.returned": PlanReturnedPayload,
    # Placement traversal — all four alternative.* events share one shape
    "placement.alternative_started": PlacementAlternativeEventPayload,
    "placement.alternative_full": PlacementAlternativeEventPayload,
    "placement.alternative_partial": PlacementAlternativeEventPayload,
    "placement.alternative_abandoned": PlacementAlternativeEventPayload,
    "placement.exhausted": PlacementExhaustedPayload,
    "job_group.assembled": JobGroupAssembledPayload,
    # Chain lifecycle
    "chain.attempt_started": ChainAttemptStartedPayload,
    "chain.failed": ChainFailedPayload,
    "chain.completed": ChainCompletedPayload,
    # Ratio
    "ratio.violated": RatioViolatedPayload,
    # Outcomes
    "outcome.recorded": OutcomeRecordedPayload,
}


def payload_model_for(event_type: str) -> type[_PayloadBase]:
    """Return the Pydantic payload model for a given event type.

    Raises ValueError if the type is not in the canonical registry.
    """
    if event_type not in PAYLOAD_REGISTRY:
        raise ValueError(
            f"Unknown event type: {event_type!r}. Canonical types are: {sorted(PAYLOAD_REGISTRY)}"
        )
    return PAYLOAD_REGISTRY[event_type]


def validate_payload(event_type: str, payload: dict[str, Any]) -> _PayloadBase:
    """Validate a raw payload dict against its registered model.

    Returns the parsed model; raises ValidationError on shape mismatch.
    """
    return payload_model_for(event_type).model_validate(payload)


__all__ = [
    "ALL_EVENT_TYPES",
    "ChainAttemptStartedPayload",
    "ChainCompletedPayload",
    "ChainFailedPayload",
    "EventType",
    "JobCompletedPayload",
    "JobFailedPayload",
    "JobGroupAssembledPayload",
    "JobSubmittedPayload",
    "OutcomeRecordedPayload",
    "PAYLOAD_REGISTRY",
    "PlacementAlternativeEventPayload",
    "PlacementExhaustedPayload",
    "PlanRequestedPayload",
    "PlanReturnedPayload",
    "RatioViolatedPayload",
    "payload_model_for",
    "validate_payload",
]
