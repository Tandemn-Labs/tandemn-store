"""Thin Postgres client wrapper.

Phase 1a: connectivity only. Real session management, transactions, and
typed query helpers land in Phase 1b alongside the SQLAlchemy models.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DEFAULT_URL = "postgresql+psycopg://tandemn:tandemn@localhost:55432/tandemn"


class PostgresClient:
    """Owns the SQLAlchemy engine. One per process.

    For Phase 1a this is a connectivity smoke wrapper. It will grow a
    Session factory and a repository surface in Phase 1b.
    """

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("TANDEMN_POSTGRES_URL", DEFAULT_URL)
        self._engine: Engine = create_engine(
            self.url,
            pool_pre_ping=True,
            future=True,
        )

    @property
    def engine(self) -> Engine:
        return self._engine

    def ping(self) -> bool:
        """Return True if the database accepts a trivial query."""
        with self._engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
