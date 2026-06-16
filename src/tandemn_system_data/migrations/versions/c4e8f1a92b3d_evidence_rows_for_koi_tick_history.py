"""evidence_rows for Koi tick history

Revision ID: c4e8f1a92b3d
Revises: 7bafcc8bf60b
Create Date: 2026-06-15

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4e8f1a92b3d"
down_revision: str | None = "7bafcc8bf60b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_rows",
        sa.Column("row_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("tick", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("rank_id", sa.Text(), nullable=False),
        sa.Column("deploy_timestamp_utc", sa.Float(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("row_id"),
    )
    op.create_index("ix_evidence_rows_user_tick", "evidence_rows", ["user_id", "tick"])
    op.create_index(
        "ix_evidence_rows_user_job_tick", "evidence_rows", ["user_id", "job_id", "tick"]
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_rows_user_job_tick", table_name="evidence_rows")
    op.drop_index("ix_evidence_rows_user_tick", table_name="evidence_rows")
    op.drop_table("evidence_rows")
