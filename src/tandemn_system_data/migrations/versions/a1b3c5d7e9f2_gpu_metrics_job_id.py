"""gpu_metrics deployment_id -> job_id

Revision ID: a1b3c5d7e9f2
Revises: f0a2c4e6d8b1
Create Date: 2026-07-06

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a1b3c5d7e9f2"
down_revision: str | None = "f0a2c4e6d8b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The pool DGD name was just a k8s encoding of (job, rank); store the
    # spine key instead. (job_id, rank_id, ts) also covers job-only scans.
    op.alter_column("gpu_metrics", "deployment_id", new_column_name="job_id")
    op.drop_index("ix_gpu_metrics_deployment_ts", table_name="gpu_metrics")
    op.drop_index("ix_gpu_metrics_rank_ts", table_name="gpu_metrics")
    op.create_index("ix_gpu_metrics_job_rank_ts", "gpu_metrics", ["job_id", "rank_id", "ts"])


def downgrade() -> None:
    op.drop_index("ix_gpu_metrics_job_rank_ts", table_name="gpu_metrics")
    op.alter_column("gpu_metrics", "job_id", new_column_name="deployment_id")
    op.create_index("ix_gpu_metrics_deployment_ts", "gpu_metrics", ["deployment_id", "ts"])
    op.create_index("ix_gpu_metrics_rank_ts", "gpu_metrics", ["rank_id", "ts"])
