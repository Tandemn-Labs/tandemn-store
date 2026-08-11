"""SQLAlchemy ORM for the canonical spine.

Mirrors tandemn_system_data.models 1:1. Re-exports the Base + every
table class so callers can write:

    from tandemn_system_data.db import Base, JobRow, RankRow
"""

from __future__ import annotations

from tandemn_system_data.db.orm import (
    ALL_TABLES,
    Base,
    CredentialsRow,
    EventConsumerOffsetRow,
    EventRow,
    EvidenceRowRow,
    GpuMetricRow,
    JobRow,
    KoiCausalEdgeRow,
    KoiCausalMechanismRow,
    KoiCausalNodeRow,
    ModelCatalogRow,
    PlanRow,
    RankRow,
    ResourceMapRow,
    UserRow,
)

__all__ = [
    "ALL_TABLES",
    "Base",
    "CredentialsRow",
    "EventConsumerOffsetRow",
    "EventRow",
    "EvidenceRowRow",
    "GpuMetricRow",
    "JobRow",
    "KoiCausalEdgeRow",
    "KoiCausalMechanismRow",
    "KoiCausalNodeRow",
    "ModelCatalogRow",
    "PlanRow",
    "RankRow",
    "ResourceMapRow",
    "UserRow",
]
