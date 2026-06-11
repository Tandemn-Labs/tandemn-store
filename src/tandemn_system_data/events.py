"""Event envelope + typed payload registry.

Events are Postgres rows. Writers append to the `events` table; consumers
read by cursor from `event_consumer_offsets` and are idempotent on `event_id`.

Catalog matches the MVP lifecycle:
  jobs    waiting -> running <-> paused -> finished
  plans   created -> applied
  chains  launching -> running -> stopped | failed
  ticks   correlation events only (no koi_ticks table)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from tandemn_system_data.models._base import CanonicalModel
from tandemn_system_data.models.enums import ActionType, ChainRole

EventType = Literal[
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
]

ALL_EVENT_TYPES: tuple[str, ...] = (
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
)


class _PayloadBase(CanonicalModel):
    """All payloads forbid extras so the wire format stays tight."""


class JobSubmittedPayload(_PayloadBase):
    job_id: str
    user_id: str


class JobPlacedPayload(_PayloadBase):
    """A plan action moved the job waiting -> running."""

    job_id: str
    user_id: str
    plan_id: str


class JobPausedPayload(_PayloadBase):
    """A plan action preempted the job (running -> paused)."""

    job_id: str
    user_id: str
    plan_id: str | None = None


class JobResumedPayload(_PayloadBase):
    """A plan action placed a paused job back (paused -> running)."""

    job_id: str
    user_id: str
    plan_id: str | None = None


class JobFinishedPayload(_PayloadBase):
    job_id: str
    user_id: str
    # NULL/None = success; a reason code (FAILED, CANCELLED, ...) otherwise.
    finish_reason: str | None = None
    detail: str | None = None


class TickStartedPayload(_PayloadBase):
    # tick_id is a correlation ID only; ticks are not entities.
    tick_id: str
    user_id: str
    waiting_job_count: int = 0
    running_job_count: int = 0


class TickCompletedPayload(_PayloadBase):
    tick_id: str
    user_id: str
    plan_id: str | None = None  # None when the tick produced no plan


class PlanCreatedPayload(_PayloadBase):
    plan_id: str
    user_id: str
    tick_id: str | None = None
    # job_id -> action type, mirrors actions_json for cheap filtering.
    actions: dict[str, ActionType]


class PlanAppliedPayload(_PayloadBase):
    plan_id: str
    user_id: str


class ChainLaunchedPayload(_PayloadBase):
    chain_id: str
    job_id: str
    plan_id: str | None = None
    role: ChainRole
    shape_json: dict[str, Any] = Field(default_factory=dict)
    target_node: str | None = None


class ChainRunningPayload(_PayloadBase):
    chain_id: str
    job_id: str


class ChainStoppedPayload(_PayloadBase):
    """Torn down on purpose: job finished, preempted, or swapped."""

    chain_id: str
    job_id: str
    reason_code: str | None = None


class ChainFailedPayload(_PayloadBase):
    chain_id: str
    job_id: str
    reason_code: str
    detail: str | None = None


PAYLOAD_REGISTRY: dict[str, type[_PayloadBase]] = {
    "job.submitted": JobSubmittedPayload,
    "job.placed": JobPlacedPayload,
    "job.paused": JobPausedPayload,
    "job.resumed": JobResumedPayload,
    "job.finished": JobFinishedPayload,
    "tick.started": TickStartedPayload,
    "tick.completed": TickCompletedPayload,
    "plan.created": PlanCreatedPayload,
    "plan.applied": PlanAppliedPayload,
    "chain.launched": ChainLaunchedPayload,
    "chain.running": ChainRunningPayload,
    "chain.stopped": ChainStoppedPayload,
    "chain.failed": ChainFailedPayload,
}


def payload_model_for(event_type: str) -> type[_PayloadBase]:
    """Return the Pydantic payload model for a given event type."""
    if event_type not in PAYLOAD_REGISTRY:
        raise ValueError(
            f"Unknown event type: {event_type!r}. Canonical types are: {sorted(PAYLOAD_REGISTRY)}"
        )
    return PAYLOAD_REGISTRY[event_type]


def validate_payload(event_type: str, payload: dict[str, Any]) -> _PayloadBase:
    """Validate a raw payload dict against its registered model."""
    return payload_model_for(event_type).model_validate(payload)


__all__ = [
    "ALL_EVENT_TYPES",
    "PAYLOAD_REGISTRY",
    "ChainFailedPayload",
    "ChainLaunchedPayload",
    "ChainRunningPayload",
    "ChainStoppedPayload",
    "EventType",
    "JobFinishedPayload",
    "JobPausedPayload",
    "JobPlacedPayload",
    "JobResumedPayload",
    "JobSubmittedPayload",
    "PlanAppliedPayload",
    "PlanCreatedPayload",
    "TickCompletedPayload",
    "TickStartedPayload",
    "payload_model_for",
    "validate_payload",
]
