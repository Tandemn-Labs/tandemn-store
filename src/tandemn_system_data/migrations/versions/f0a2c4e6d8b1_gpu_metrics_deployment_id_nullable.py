"""gpu_metrics deployment_id nullable

Revision ID: f0a2c4e6d8b1
Revises: e8d0a2c4b6f7
Create Date: 2026-07-06

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0a2c4e6d8b1"
down_revision: str | None = "e8d0a2c4b6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The fleet collector records idle GPUs (no owning worker) with a NULL
    # deployment_id instead of borrowing a deployment's id.
    op.alter_column("gpu_metrics", "deployment_id", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("gpu_metrics", "deployment_id", existing_type=sa.Text(), nullable=False)
