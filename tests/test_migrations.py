r"""Integration: Alembic baseline applies cleanly and matches the ORM.

Requires \`make up\` (docker-compose stack) to be running.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import inspect

from tandemn_system_data.clients import PostgresClient
from tandemn_system_data.db import ALL_TABLES, Base

pytestmark = pytest.mark.integration


# Repo root holds alembic.ini.
REPO_ROOT = Path(__file__).resolve().parents[1]


def _alembic(*args: str) -> None:
    """Run an alembic subcommand and assert exit 0."""
    result = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} failed\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


@pytest.fixture
def clean_db() -> None:
    """Drop everything Alembic might have left behind, then yield."""
    client = PostgresClient()
    Base.metadata.drop_all(client.engine)
    # Also drop the alembic_version table if present.
    with client.engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    yield


def test_baseline_upgrade_creates_all_canonical_tables(clean_db):
    _alembic("upgrade", "head")

    client = PostgresClient()
    insp = inspect(client.engine)
    db_tables = set(insp.get_table_names())

    expected = {row.__tablename__ for row in ALL_TABLES}
    assert expected.issubset(db_tables), f"missing: {expected - db_tables}, found: {db_tables}"
    # Alembic also creates its own version-tracking table.
    assert "alembic_version" in db_tables


def test_baseline_downgrade_drops_canonical_tables(clean_db):
    _alembic("upgrade", "head")
    _alembic("downgrade", "base")

    client = PostgresClient()
    insp = inspect(client.engine)
    db_tables = set(insp.get_table_names())

    for row in ALL_TABLES:
        assert row.__tablename__ not in db_tables, (
            f"{row.__tablename__} should be dropped after downgrade"
        )


def test_orm_and_migration_are_in_sync(clean_db):
    """`alembic check` reports no diff between the ORM and the DB after upgrade."""
    _alembic("upgrade", "head")
    result = subprocess.run(
        ["uv", "run", "alembic", "check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "No new upgrade operations detected" in (result.stdout + result.stderr)
