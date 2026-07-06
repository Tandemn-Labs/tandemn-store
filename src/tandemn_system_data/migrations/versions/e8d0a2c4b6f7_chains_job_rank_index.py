"""chains job->rank index

Revision ID: e8d0a2c4b6f7
Revises: d6b8e0f2a4c5
Create Date: 2026-07-03

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8d0a2c4b6f7"
down_revision: str | None = "d6b8e0f2a4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Koi's rank_id lives inside chains.shape_json (ranks have no spine
    # table); this backs job -> rank chain lookups.
    op.create_index(
        "ix_chains_job_rank",
        "chains",
        ["job_id", sa.text("(shape_json ->> 'rank_id')")],
    )


def downgrade() -> None:
    op.drop_index("ix_chains_job_rank", table_name="chains")
