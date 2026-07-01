"""gpu_metrics timeseries

Revision ID: b2d4f6a8c0e1
Revises: a7c3e9f1b2d8
Create Date: 2026-06-30

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2d4f6a8c0e1"
down_revision: str | None = "a7c3e9f1b2d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gpu_metrics",
        sa.Column("metric_id", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deployment_id", sa.Text(), nullable=False),
        sa.Column("gpu_uuid", sa.Text(), nullable=False),
        sa.Column("rank_id", sa.Text(), nullable=True),
        sa.Column("chain_id", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("local_rank", sa.Text(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column("node_name", sa.Text(), nullable=True),
        sa.Column("instance_type", sa.Text(), nullable=True),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("metric_id"),
    )
    op.create_index("ix_gpu_metrics_deployment_ts", "gpu_metrics", ["deployment_id", "ts"])
    op.create_index("ix_gpu_metrics_gpu_ts", "gpu_metrics", ["gpu_uuid", "ts"])
    op.create_index("ix_gpu_metrics_chain_ts", "gpu_metrics", ["chain_id", "ts"])
    op.create_index("ix_gpu_metrics_rank_ts", "gpu_metrics", ["rank_id", "ts"])
    op.create_index("ix_gpu_metrics_role_ts", "gpu_metrics", ["role", "ts"])


def downgrade() -> None:
    op.drop_index("ix_gpu_metrics_role_ts", table_name="gpu_metrics")
    op.drop_index("ix_gpu_metrics_rank_ts", table_name="gpu_metrics")
    op.drop_index("ix_gpu_metrics_chain_ts", table_name="gpu_metrics")
    op.drop_index("ix_gpu_metrics_gpu_ts", table_name="gpu_metrics")
    op.drop_index("ix_gpu_metrics_deployment_ts", table_name="gpu_metrics")
    op.drop_table("gpu_metrics")
