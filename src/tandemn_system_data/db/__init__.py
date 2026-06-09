"""SQLAlchemy ORM for the canonical spine.

Mirrors tandemn_system_data.models 1:1. Re-exports the Base + every
table class so callers can write:

    from tandemn_system_data.db import Base, JobRow, ChainRow
"""

from __future__ import annotations

from tandemn_system_data.db.orm import (
    ALL_TABLES,
    AttemptRow,
    Base,
    ChainRow,
    CredentialsRow,
    EventConsumerOffsetRow,
    EventRow,
    JobRow,
    KoiTickRow,
    OutcomeRow,
    PlanJobRow,
    PlanRow,
    RankRow,
    ResourceMapRow,
    UserRow,
)

__all__ = [
    "ALL_TABLES",
    "AttemptRow",
    "Base",
    "ChainRow",
    "CredentialsRow",
    "EventConsumerOffsetRow",
    "PlanRow",
    "EventRow",
    "JobRow",
    "KoiTickRow",
    "OutcomeRow",
    "PlanJobRow",
    "ResourceMapRow",
    "RankRow",
    "UserRow",
]
