"""Event envelope + typed payload registry.

Events are Postgres rows. Writers append to the `events` table; consumers
read by cursor from `event_consumer_offsets` and are idempotent on `event_id`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from tandemn_system_data.models._base import CanonicalModel
from tandemn_system_data.models.enums import ChainRole, JobStatus, OutcomeStatus, RankStatus

EventType = Literal[
    "job.submitted",
    "job.completed",
    "job.failed",
    "tick.started",
    "tick.completed",
    "plan.created",
    "plan.throughput_met",
    "plan.exhausted",
    "rank.started",
    "rank.realized",
    "rank.completed",
    "rank.failed",
    "job_group.assembled",
    "chain.attempt_started",
    "chain.failed",
    "chain.completed",
    "ratio.violated",
    "outcome.recorded",
]

ALL_EVENT_TYPES: tuple[str, ...] = (
    "job.submitted",
    "job.completed",
    "job.failed",
    "tick.started",
    "tick.completed",
    "plan.created",
    "plan.throughput_met",
    "plan.exhausted",
    "rank.started",
    "rank.realized",
    "rank.completed",
    "rank.failed",
    "job_group.assembled",
    "chain.attempt_started",
    "chain.failed",
    "chain.completed",
    "ratio.violated",
    "outcome.recorded",
)


class _PayloadBase(CanonicalModel):
    """All payloads forbid extras so the wire format stays tight."""


class JobSubmittedPayload(_PayloadBase):
    job_id: str
    user_id: str


class JobCompletedPayload(_PayloadBase):
    job_id: str
    user_id: str
    final_status: JobStatus = JobStatus.COMPLETED


class JobFailedPayload(_PayloadBase):
    job_id: str
    user_id: str
    reason_code: str
    detail: str | None = None


class TickStartedPayload(_PayloadBase):
    tick_id: str
    user_id: str
    waiting_job_count: int = 0
    running_job_count: int = 0


class TickCompletedPayload(_PayloadBase):
    tick_id: str
    user_id: str


class PlanCreatedPayload(_PayloadBase):
    plan_id: str
    user_id: str
    # Correlation to the tick.started/tick.completed events of the pass
    # that produced this plan; ticks are not entities.
    tick_id: str | None = None
    job_ids: list[str]


class PlanThroughputMetPayload(_PayloadBase):
    plan_id: str
    achieved_throughput_tps: float
    required_throughput_tps: float


class PlanExhaustedPayload(_PayloadBase):
    plan_id: str
    achieved_throughput_tps: float
    required_throughput_tps: float


class RankEventPayload(_PayloadBase):
    plan_id: str
    rank_id: str
    rank_index: int
    status: RankStatus | None = None


class RankRealizedPayload(_PayloadBase):
    plan_id: str
    rank_id: str
    rank_index: int
    estimated_throughput_tps: float | None = None
    realized_throughput_tps: float
    cumulative_realized_throughput_tps: float


class JobGroupAssembledPayload(_PayloadBase):
    plan_id: str
    achieved_throughput_tps: float
    required_throughput_tps: float
    chain_ids: list[str]


class ChainAttemptStartedPayload(_PayloadBase):
    chain_id: str
    attempt_id: str
    rank_id: str
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


class RatioViolatedPayload(_PayloadBase):
    rank_id: str
    expected_pd_ratio: float
    realized_pd_ratio: float
    realized_prefill_chains: int
    realized_decode_chains: int


class OutcomeRecordedPayload(_PayloadBase):
    outcome_id: str
    chain_id: str
    status: OutcomeStatus
    reason_code: str | None = None


PAYLOAD_REGISTRY: dict[str, type[_PayloadBase]] = {
    "job.submitted": JobSubmittedPayload,
    "job.completed": JobCompletedPayload,
    "job.failed": JobFailedPayload,
    "tick.started": TickStartedPayload,
    "tick.completed": TickCompletedPayload,
    "plan.created": PlanCreatedPayload,
    "plan.throughput_met": PlanThroughputMetPayload,
    "plan.exhausted": PlanExhaustedPayload,
    "rank.started": RankEventPayload,
    "rank.realized": RankRealizedPayload,
    "rank.completed": RankEventPayload,
    "rank.failed": RankEventPayload,
    "job_group.assembled": JobGroupAssembledPayload,
    "chain.attempt_started": ChainAttemptStartedPayload,
    "chain.failed": ChainFailedPayload,
    "chain.completed": ChainCompletedPayload,
    "ratio.violated": RatioViolatedPayload,
    "outcome.recorded": OutcomeRecordedPayload,
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
    "PlanCreatedPayload",
    "PlanExhaustedPayload",
    "PlanThroughputMetPayload",
    "RankEventPayload",
    "RankRealizedPayload",
    "RatioViolatedPayload",
    "TickCompletedPayload",
    "TickStartedPayload",
    "payload_model_for",
    "validate_payload",
]
