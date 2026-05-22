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
    DecisionRow,
    EventRow,
    JobRow,
    OutcomeRow,
    PlacementAlternativeRow,
    PlanRow,
    ResourceMapRow,
    TenantRow,
)

__all__ = [
    "ALL_TABLES",
    "AttemptRow",
    "Base",
    "ChainRow",
    "CredentialsRow",
    "DecisionRow",
    "EventRow",
    "JobRow",
    "OutcomeRow",
    "PlacementAlternativeRow",
    "PlanRow",
    "ResourceMapRow",
    "TenantRow",
]
