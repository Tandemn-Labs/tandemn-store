"""model_catalogs

Revision ID: b4d6f8a0c2e3
Revises: a1b3c5d7e9f2
Create Date: 2026-07-06

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4d6f8a0c2e3"
down_revision: str | None = "a1b3c5d7e9f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_catalogs",
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("catalog_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("model_id"),
    )


def downgrade() -> None:
    op.drop_table("model_catalogs")
