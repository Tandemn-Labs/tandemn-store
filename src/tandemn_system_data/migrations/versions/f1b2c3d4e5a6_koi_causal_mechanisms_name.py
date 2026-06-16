"""koi_causal_mechanisms name column

Revision ID: f1b2c3d4e5a6
Revises: e8a3c1d25f9b
Create Date: 2026-06-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1b2c3d4e5a6"
down_revision: str | None = "e8a3c1d25f9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "koi_causal_mechanisms",
        sa.Column("name", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("koi_causal_mechanisms", "name")
