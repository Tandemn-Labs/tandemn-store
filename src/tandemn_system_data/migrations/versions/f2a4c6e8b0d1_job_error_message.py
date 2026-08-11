"""add user-visible job error messages

Revision ID: f2a4c6e8b0d1
Revises: c7d9e1f3a5b8
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a4c6e8b0d1"
down_revision: str | None = "c7d9e1f3a5b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "error_message")
