"""Shared Pydantic config and base class for canonical models.

All canonical models use Pydantic v2 with strict typing, no extras
allowed, and timezone-aware datetimes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict


def utc_now() -> datetime:
    """Default factory for timezone-aware UTC datetimes."""
    return datetime.now(UTC)


class CanonicalModel(BaseModel):
    """Base class for every canonical entity.

    - `extra="forbid"` keeps the wire format honest.
    - `frozen=False` so consumers can mutate before persisting; once
      written to Postgres, the row is the source of truth.
    - `from_attributes=True` lets us materialize a Pydantic model from
      a SQLAlchemy ORM row.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
        from_attributes=True,
        str_strip_whitespace=True,
    )
