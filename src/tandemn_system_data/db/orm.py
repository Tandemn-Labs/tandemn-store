"""SQLAlchemy ORM for the canonical spine — mirrors DATA_ARCHITECTURE.md §5.

One file on purpose: the schema is small enough that keeping all tables
together is easier to keep mutually consistent than splitting per entity.

Conventions:
  - Primary keys are TEXT (prefixed ULID; see tandemn_system_data.ids).
  - JSONB everywhere structure is intentionally schemaless.
  - All timestamps are TIMESTAMPTZ (tz-aware).
  - Foreign keys mirror the canonical hierarchy in §4.
  - GIN indexes on heavy JSONB columns per the §5 note.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,  # noqa: F401  — reserved for future use
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for every canonical table."""


# ---------------------------------------------------------------------------
# §5: users
# ---------------------------------------------------------------------------


class UserRow(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# §5: resource_maps
# ---------------------------------------------------------------------------


class ResourceMapRow(Base):
    __tablename__ = "resource_maps"

    resource_map_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_resource_maps_user_captured", "user_id", "captured_at"),
        # GIN index for path/value queries against the snapshot blob.
        Index(
            "ix_resource_maps_snapshot_gin",
            "snapshot_json",
            postgresql_using="gin",
            postgresql_ops={"snapshot_json": "jsonb_path_ops"},
        ),
    )


# ---------------------------------------------------------------------------
# §5: jobs
# ---------------------------------------------------------------------------


class JobRow(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # §5: input_source / output_target are JSONB pointers, NEVER the data itself.
    input_source: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_target: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_jobs_user_created", "user_id", "created_at"),
        Index("ix_jobs_status", "status"),
    )


# ---------------------------------------------------------------------------
# §5: plans
# ---------------------------------------------------------------------------


class PlanRow(Base):
    __tablename__ = "plans"

    plan_id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_id: Mapped[str] = mapped_column(
        Text, ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    koi_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rationale_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    slo_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_plans_job", "job_id"),)


# ---------------------------------------------------------------------------
# §5 + §6: placement_alternatives
# ---------------------------------------------------------------------------


class PlacementAlternativeRow(Base):
    __tablename__ = "placement_alternatives"

    alternative_id: Mapped[str] = mapped_column(Text, primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        Text, ForeignKey("plans.plan_id", ondelete="CASCADE"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    # §5: pd_ratio NULL for aggregate; > 0 for pd_disaggregated.
    pd_ratio: Mapped[float | None] = mapped_column(Numeric(asdecimal=False), nullable=True)
    sizing_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    estimated_throughput_tps: Mapped[float | None] = mapped_column(
        Numeric(asdecimal=False), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_placement_alternatives_plan_rank", "plan_id", "rank"),)


# ---------------------------------------------------------------------------
# §5: chains
# ---------------------------------------------------------------------------


class ChainRow(Base):
    __tablename__ = "chains"

    chain_id: Mapped[str] = mapped_column(Text, primary_key=True)
    alternative_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("placement_alternatives.alternative_id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    shape_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    parallelism_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    target_node: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_chains_alternative_role", "alternative_id", "role"),
        Index("ix_chains_status", "status"),
    )


# ---------------------------------------------------------------------------
# §5: attempts
# ---------------------------------------------------------------------------


class AttemptRow(Base):
    __tablename__ = "attempts"

    attempt_id: Mapped[str] = mapped_column(Text, primary_key=True)
    chain_id: Mapped[str] = mapped_column(
        Text, ForeignKey("chains.chain_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("ix_attempts_chain", "chain_id"),)


# ---------------------------------------------------------------------------
# §5: outcomes
# ---------------------------------------------------------------------------


class OutcomeRow(Base):
    __tablename__ = "outcomes"

    outcome_id: Mapped[str] = mapped_column(Text, primary_key=True)
    chain_id: Mapped[str] = mapped_column(
        Text, ForeignKey("chains.chain_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_outcomes_chain", "chain_id"),)


# ---------------------------------------------------------------------------
# §5: events (durable audit log; §8: CP record alongside AP delivery)
# ---------------------------------------------------------------------------


class EventRow(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    chain_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # Events are NOT foreign-key-bound to jobs/chains because the audit
        # log must survive cascade deletes of upstream rows. Index for the
        # common "show me everything about job_xyz" query (§12).
        Index("ix_events_job_created", "job_id", "created_at"),
        Index("ix_events_chain_created", "chain_id", "created_at"),
        Index("ix_events_user_created", "user_id", "created_at"),
        Index("ix_events_type_created", "type", "created_at"),
    )


# ---------------------------------------------------------------------------
# §5 + §7: credentials
# ---------------------------------------------------------------------------


class CredentialsRow(Base):
    __tablename__ = "credentials"

    credentials_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # §5: encrypted at rest in production; raw bytes column at the DB layer.
    secret_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_from: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_credentials_user", "user_id"),
        Index("ix_credentials_expires", "expires_at"),
    )


# ---------------------------------------------------------------------------
# Convenience export
# ---------------------------------------------------------------------------


ALL_TABLES: tuple[type[Base], ...] = (
    UserRow,
    ResourceMapRow,
    JobRow,
    PlanRow,
    PlacementAlternativeRow,
    ChainRow,
    AttemptRow,
    OutcomeRow,
    EventRow,
    CredentialsRow,
)
