"""Shared fixtures for integration tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tandemn_system_data.clients import PostgresClient

REPO_ROOT = Path(__file__).resolve().parents[1]


def apply_baseline(pg_client: PostgresClient) -> None:
    """Drop the spine and reapply the Alembic baseline — the same
    migration path production uses."""
    from tandemn_system_data.db import Base

    Base.metadata.drop_all(pg_client.engine)
    with pg_client.engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module")
def pg_client() -> PostgresClient:
    return PostgresClient()


@pytest.fixture(scope="module")
def fresh_schema(pg_client: PostgresClient) -> None:
    apply_baseline(pg_client)
