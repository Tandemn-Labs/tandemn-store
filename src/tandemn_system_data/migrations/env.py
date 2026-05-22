"""Alembic environment.

Wires Alembic to the canonical spine's SQLAlchemy metadata so
`alembic revision --autogenerate` diffs the ORM (Base.metadata) against
the live database.

DB URL resolution order:
  1. TANDEMN_POSTGRES_URL env var
  2. sqlalchemy.url from alembic.ini
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from tandemn_system_data.db import Base

# ---------------------------------------------------------------------------
# Alembic config
# ---------------------------------------------------------------------------

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Env override beats the ini.
_env_url = os.getenv("TANDEMN_POSTGRES_URL")
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)

target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations without an Engine — emits SQL to stdout."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live engine."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
