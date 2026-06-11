"""baseline: canonical spine per DATA_ARCHITECTURE.md

Revision ID: 7bafcc8bf60b
Revises:
Create Date: 2026-05-22 14:22:12.654026

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7bafcc8bf60b"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("job_id", sa.Text(), nullable=True),
        sa.Column("chain_id", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_events_chain_created", "events", ["chain_id", "created_at"])
    op.create_index("ix_events_job_created", "events", ["job_id", "created_at"])
    op.create_index("ix_events_user_created", "events", ["user_id", "created_at"])
    op.create_index("ix_events_type_created", "events", ["type", "created_at"])

    op.create_table(
        "event_consumer_offsets",
        sa.Column("consumer_name", sa.Text(), nullable=False),
        sa.Column("last_event_id", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("consumer_name"),
    )

    op.create_table(
        "users",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "credentials",
        sa.Column("credentials_ref", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("scope_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secret_payload", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_from", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("credentials_ref"),
    )
    op.create_index("ix_credentials_expires", "credentials", ["expires_at"])
    op.create_index("ix_credentials_user", "credentials", ["user_id"])

    op.create_table(
        "jobs",
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("spec_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_source", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_target", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("finish_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_user_created", "jobs", ["user_id", "created_at"])

    op.create_table(
        "plans",
        sa.Column("plan_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("koi_version", sa.String(length=64), nullable=True),
        sa.Column("tick_rationale", sa.Text(), nullable=False),
        sa.Column("actions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id"),
    )
    op.create_index("ix_plans_status", "plans", ["status"])
    op.create_index("ix_plans_user_created", "plans", ["user_id", "created_at"])

    op.create_table(
        "chains",
        sa.Column("chain_id", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("plan_id", sa.Text(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("shape_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("target_node", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chain_id"),
    )
    op.create_index("ix_chains_job", "chains", ["job_id"])
    op.create_index("ix_chains_status", "chains", ["status"])


def downgrade() -> None:
    op.drop_index("ix_chains_status", table_name="chains")
    op.drop_index("ix_chains_job", table_name="chains")
    op.drop_table("chains")
    op.drop_index("ix_plans_user_created", table_name="plans")
    op.drop_index("ix_plans_status", table_name="plans")
    op.drop_table("plans")
    op.drop_index("ix_jobs_user_created", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_credentials_user", table_name="credentials")
    op.drop_index("ix_credentials_expires", table_name="credentials")
    op.drop_table("credentials")
    op.drop_table("users")
    op.drop_index("ix_events_type_created", table_name="events")
    op.drop_index("ix_events_user_created", table_name="events")
    op.drop_index("ix_events_job_created", table_name="events")
    op.drop_index("ix_events_chain_created", table_name="events")
    op.drop_table("event_consumer_offsets")
    op.drop_table("events")
