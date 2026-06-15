"""tandemn_system_data — canonical state for Tandemn (Orca + Koi only).

This package owns:
  - Pydantic models for all canonical entities
  - SQLAlchemy ORM mirroring those models
  - Alembic migrations
  - Postgres client, stores (JobStore, PlanStore, CredentialStore, ...),
    Postgres event log, resource map wire contract
  - Canonical ID generator and event envelope

Workers MUST NOT import this package. See DATA_ARCHITECTURE.md §2.
"""

__version__ = "0.1.0"
