"""Postgres client: SQLAlchemy engine + session factory + transactional helper.

Owns the engine and a sessionmaker. Callers obtain a Session via
`client.session()` (a context manager) or `client.begin()` for
auto-commit semantics.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_URL = "postgresql+psycopg://tandemn:tandemn@localhost:55432/tandemn"


class PostgresClient:
    """Owns the SQLAlchemy engine and a sessionmaker. One per process.

    Usage:
        client = PostgresClient()
        with client.session() as s:           # read-only or manual commit
            s.execute(...)
        with client.begin() as s:             # auto-commit / rollback
            s.add(row)
    """

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("TANDEMN_POSTGRES_URL", DEFAULT_URL)
        self._engine: Engine = create_engine(
            self.url,
            pool_pre_ping=True,
            future=True,
        )
        self._session_factory = sessionmaker(
            bind=self._engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
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

    # -----------------------------------------------------------------
    # Sessions
    # -----------------------------------------------------------------

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a Session. Caller is responsible for commit/rollback."""
        s = self._session_factory()
        try:
            yield s
        finally:
            s.close()

    @contextmanager
    def begin(self) -> Iterator[Session]:
        """Yield a Session inside an explicit transaction.

        Commits on clean exit, rolls back on exception.
        """
        s = self._session_factory()
        try:
            with s.begin():
                yield s
        finally:
            s.close()
