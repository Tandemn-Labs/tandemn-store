"""Canonical enums shared across models.

All string values are stable wire/storage values — they are persisted in
Postgres and emitted in events. Do not rename without a migration.
"""

from __future__ import annotations

from enum import StrEnum


class JobKind(StrEnum):
    BATCH = "batch"
    ONLINE = "online"


class JobStatus(StrEnum):
    """The full MVP lifecycle. New jobs start WAITING; a plan action
    moves them (place: waiting->running, preempt: running->paused,
    defer/keep: no change). FINISHED is the only terminal state;
    jobs.finish_reason distinguishes success (NULL) from failure."""

    WAITING = "waiting"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"


class ActionType(StrEnum):
    """Per-job action inside a plan's actions_json."""

    PLACE = "place"  # waiting -> running, launch ladder
    KEEP = "keep"  # stay running, no change
    DEFER = "defer"  # stay waiting
    PREEMPT = "preempt"  # running -> paused, tear down ranks
    SWAP = "swap"  # stay running, relaunch on a new ladder


class RankRole(StrEnum):
    PREFILL = "prefill"
    DECODE = "decode"
    AGGREGATE = "aggregate"


class RankStatus(StrEnum):
    LAUNCHING = "launching"
    RUNNING = "running"
    STOPPED = "stopped"  # torn down on purpose (job finished/preempted/swapped)
    FAILED = "failed"


class ReasonCode(StrEnum):
    """Standard reason codes for rank / job failures.

    Open-ended on purpose — emerging codes can be added without a
    migration since the columns are text.
    """

    HEARTBEAT_TIMEOUT = "HEARTBEAT_TIMEOUT"
    LAUNCH_FAILED = "LAUNCH_FAILED"
    OOM = "OOM"
    PROCESS_CRASH = "PROCESS_CRASH"
    NODE_LOST = "NODE_LOST"
    PREEMPTED = "PREEMPTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    MODEL_CATALOG_INVALID = "MODEL_CATALOG_INVALID"
