"""koi_causal_* tables in Postgres

Revision ID: e8a3c1d25f9b
Revises: d5f9a2b14c7e
Create Date: 2026-06-15

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8a3c1d25f9b"
down_revision: str | None = "d5f9a2b14c7e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "koi_causal_nodes",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("node_type", sa.String(length=8), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "node_id"),
    )
    op.create_table(
        "koi_causal_edges",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("edge_id", sa.Text(), nullable=False),
        sa.Column("src", sa.Text(), nullable=False),
        sa.Column("dst", sa.Text(), nullable=False),
        sa.Column("src_type", sa.String(length=8), nullable=False),
        sa.Column("dst_type", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("alpha", sa.Float(), nullable=False),
        sa.Column("beta", sa.Float(), nullable=False),
        sa.Column("visit_count", sa.Integer(), nullable=False),
        sa.Column("last_touched_tick", sa.Integer(), nullable=True),
        sa.Column("q_histogram_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("envs_seen_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("q3_frequency", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "edge_id"),
    )
    op.create_table(
        "koi_causal_mechanisms",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("mechanism_id", sa.Text(), nullable=False),
        sa.Column("edge_ids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scope_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("archived_reason", sa.Text(), nullable=True),
        sa.Column("alpha", sa.Float(), nullable=False),
        sa.Column("beta", sa.Float(), nullable=False),
        sa.Column("visit_count", sa.Integer(), nullable=False),
        sa.Column("last_touched_tick", sa.Integer(), nullable=True),
        sa.Column("q_histogram_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("envs_seen_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("inspection_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "mechanism_id"),
    )


def downgrade() -> None:
    op.drop_table("koi_causal_mechanisms")
    op.drop_table("koi_causal_edges")
    op.drop_table("koi_causal_nodes")
