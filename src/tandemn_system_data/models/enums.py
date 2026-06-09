"""Canonical enums shared across models.

All string values are stable wire/storage values — they are persisted in
Postgres and emitted in events. Do not rename without a migration.
"""

from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


class JobKind(StrEnum):
    BATCH = "batch"
    ONLINE = "online"


class JobStatus(StrEnum):
    SUBMITTED = "submitted"
    PLANNING = "planning"
    LAUNCHING = "launching"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Placement (DATA_ARCHITECTURE.md §6)
# ---------------------------------------------------------------------------


class PlacementStrategy(StrEnum):
    """Top-level placement strategy for a rank."""

    PD_DISAGGREGATED = "pd_disaggregated"
    AGGREGATE = "aggregate"


class RankStatus(StrEnum):
    """Status of a rank as the executor traverses it.

    Used by rank.started / rank.completed / rank.failed / rank.realized
    event payloads and by the ranks table.
    """

    PENDING = "pending"
    STARTED = "started"
    FULL = "full"
    PARTIAL = "partial"
    ABANDONED = "abandoned"
    NOT_ATTEMPTED = "not_attempted"


# ---------------------------------------------------------------------------
# Chain (§5: role: prefill | decode | aggregate)
# ---------------------------------------------------------------------------


class ChainRole(StrEnum):
    PREFILL = "prefill"
    DECODE = "decode"
    AGGREGATE = "aggregate"


class ChainStatus(StrEnum):
    PENDING = "pending"
    LAUNCHING = "launching"
    RUNNING = "running"
    DRAINING = "draining"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Attempt
# ---------------------------------------------------------------------------


class AttemptStatus(StrEnum):
    STARTED = "started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ReasonCode(StrEnum):
    """Standard reason codes for chain / attempt failures.

    Open-ended on purpose — emerging codes can be added without a
    migration since the column is text.
    """

    HEARTBEAT_TIMEOUT = "HEARTBEAT_TIMEOUT"
    LAUNCH_FAILED = "LAUNCH_FAILED"
    OOM = "OOM"
    PROCESS_CRASH = "PROCESS_CRASH"
    NODE_LOST = "NODE_LOST"
    DRAINED = "DRAINED"
    RATIO_VIOLATED = "RATIO_VIOLATED"
    SLO_NOT_MET = "SLO_NOT_MET"


# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------


class OutcomeStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
