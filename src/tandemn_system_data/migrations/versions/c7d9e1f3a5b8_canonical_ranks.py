"""replace persisted chains with canonical ranks

Revision ID: c7d9e1f3a5b8
Revises: b4d6f8a0c2e3
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7d9e1f3a5b8"
down_revision: str | None = "b4d6f8a0c2e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("chains")
    op.create_table(
        "ranks",
        sa.Column("rank_id", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("plan_id", sa.Text(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("shape_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("n_replicas", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("n_replicas > 0", name="ck_ranks_n_replicas_positive"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("rank_id"),
    )
    op.create_index("ix_ranks_job", "ranks", ["job_id"])
    op.create_index("ix_ranks_status", "ranks", ["status"])

    op.drop_index("ix_events_chain_created", table_name="events")
    op.alter_column("events", "chain_id", new_column_name="rank_id")
    op.create_index("ix_events_rank_created", "events", ["rank_id", "created_at"])

    op.drop_index("ix_gpu_metrics_chain_ts", table_name="gpu_metrics")
    op.drop_column("gpu_metrics", "chain_id")
    op.add_column("gpu_metrics", sa.Column("chain_index", sa.Integer(), nullable=True))
    op.create_index(
        "ix_gpu_metrics_rank_chain_ts",
        "gpu_metrics",
        ["rank_id", "chain_index", "ts"],
    )


def downgrade() -> None:
    op.drop_index("ix_gpu_metrics_rank_chain_ts", table_name="gpu_metrics")
    op.drop_column("gpu_metrics", "chain_index")
    op.add_column("gpu_metrics", sa.Column("chain_id", sa.Text(), nullable=True))
    op.create_index("ix_gpu_metrics_chain_ts", "gpu_metrics", ["chain_id", "ts"])

    op.drop_index("ix_events_rank_created", table_name="events")
    op.alter_column("events", "rank_id", new_column_name="chain_id")
    op.create_index("ix_events_chain_created", "events", ["chain_id", "created_at"])

    op.drop_table("ranks")
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
    op.create_index(
        "ix_chains_job_rank",
        "chains",
        ["job_id", sa.text("(shape_json ->> 'rank_id')")],
    )
