"""SQLAlchemy ORM for the canonical spine — mirrors DATA_ARCHITECTURE.md §5.

One file on purpose: the schema is small enough that keeping all tables
together is easier to keep mutually consistent than splitting per entity.

Conventions:
  - Primary keys are TEXT (prefixed ULID; see tandemn_system_data.ids).
  - JSONB everywhere structure is intentionally schemaless.
  - All timestamps are TIMESTAMPTZ (tz-aware).
  - Foreign keys mirror the canonical hierarchy in §4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
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
    # waiting | running | paused | finished
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # NULL = success; reason code (FAILED, CANCELLED, ...) otherwise.
    finish_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    koi_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tick_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # List of per-job actions (place/keep/defer/preempt/swap); ladders
    # with expected TPS live inside — there is no ranks table.
    actions_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_plans_user_created", "user_id", "created_at"),
        Index("ix_plans_status", "status"),
    )


# ---------------------------------------------------------------------------
# §5: chains
# ---------------------------------------------------------------------------


class ChainRow(Base):
    __tablename__ = "chains"

    chain_id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_id: Mapped[str] = mapped_column(
        Text, ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False
    )
    # Provenance only (which plan placed this chain); no FK so plans and
    # chains have independent lifecycles.
    plan_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # Hardware + parallelism: {"gpu": "H100", "count": 8, "tp": 2, "pp": 4}
    shape_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    target_node: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_chains_job", "job_id"),
        Index("ix_chains_status", "status"),
    )


# ---------------------------------------------------------------------------
# §5: events (durable audit log + MVP delivery path)
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


class EventConsumerOffsetRow(Base):
    __tablename__ = "event_consumer_offsets"

    consumer_name: Mapped[str] = mapped_column(Text, primary_key=True)
    last_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
    JobRow,
    PlanRow,
    ChainRow,
    EventRow,
    EventConsumerOffsetRow,
    CredentialsRow,
)
