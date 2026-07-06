"""gpu_metrics drop worker_id

Revision ID: d6b8e0f2a4c5
Revises: b2d4f6a8c0e1
Create Date: 2026-07-03

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6b8e0f2a4c5"
down_revision: str | None = "b2d4f6a8c0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # chain_id now carries the canonical chains.chain_id (pod name fallback),
    # so a separate worker pod column is redundant with it.
    op.drop_column("gpu_metrics", "worker_id")


def downgrade() -> None:
    op.add_column("gpu_metrics", sa.Column("worker_id", sa.Text(), nullable=True))
