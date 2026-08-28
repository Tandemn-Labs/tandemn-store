"""Event envelope + typed payload registry.

Events are Postgres rows. Writers append to the `events` table; consumers
read by cursor from `event_consumer_offsets` and are idempotent on `event_id`.

Catalog matches the MVP lifecycle:
  jobs    waiting -> running <-> paused -> finished
  plans   created -> applied
  ranks   launching -> running -> stopped | failed
  ticks   correlation events only (no koi_ticks table)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from tandemn_system_data.models._base import CanonicalModel
from tandemn_system_data.models.enums import ActionType, RankRole

EventType = Literal[
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
]

ALL_EVENT_TYPES: tuple[str, ...] = (
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
)


class _PayloadBase(CanonicalModel):
    """All payloads forbid extras so the wire format stays tight."""


class JobSubmittedPayload(_PayloadBase):
    job_id: str
    user_id: str


class JobPlacePayload(_PayloadBase):
    """Orca began processing a plan's place action."""

    job_id: str
    user_id: str
    plan_id: str
    action_type: Literal["place"]


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


class RankLaunchingPayload(_PayloadBase):
    """Orca persisted desired rank state and began infrastructure launch."""

    rank_id: str
    job_id: str
    plan_id: str | None = None
    role: RankRole
    shape_json: dict[str, Any] = Field(default_factory=dict)
    n_replicas: int


class RankLaunchedPayload(_PayloadBase):
    rank_id: str
    job_id: str
    plan_id: str | None = None
    role: RankRole
    shape_json: dict[str, Any] = Field(default_factory=dict)
    n_replicas: int


class RankRunningPayload(_PayloadBase):
    rank_id: str
    job_id: str


class RankStoppedPayload(_PayloadBase):
    """Torn down on purpose: job finished, preempted, or swapped."""

    rank_id: str
    job_id: str
    reason_code: str | None = None


class RankFailedPayload(_PayloadBase):
    rank_id: str
    job_id: str
    reason_code: str
    detail: str | None = None


PAYLOAD_REGISTRY: dict[str, type[_PayloadBase]] = {
    "job.place": JobPlacePayload,
    "job.submitted": JobSubmittedPayload,
    "job.placed": JobPlacedPayload,
    "job.paused": JobPausedPayload,
    "job.resumed": JobResumedPayload,
    "job.finished": JobFinishedPayload,
    "tick.started": TickStartedPayload,
    "tick.completed": TickCompletedPayload,
    "plan.created": PlanCreatedPayload,
    "plan.applied": PlanAppliedPayload,
    "rank.launching": RankLaunchingPayload,
    "rank.launched": RankLaunchedPayload,
    "rank.running": RankRunningPayload,
    "rank.stopped": RankStoppedPayload,
    "rank.failed": RankFailedPayload,
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
    "EventType",
    "JobFinishedPayload",
    "JobPausedPayload",
    "JobPlacePayload",
    "JobPlacedPayload",
    "JobResumedPayload",
    "JobSubmittedPayload",
    "PlanAppliedPayload",
    "PlanCreatedPayload",
    "RankFailedPayload",
    "RankLaunchedPayload",
    "RankLaunchingPayload",
    "RankRunningPayload",
    "RankStoppedPayload",
    "TickCompletedPayload",
    "TickStartedPayload",
    "payload_model_for",
    "validate_payload",
]
