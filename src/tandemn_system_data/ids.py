"""Canonical prefixed ID generator.

ID format:  <prefix>_<26-char Crockford-base32 ULID>
Examples:   job_01JBM2YQYZ1KQ9C8GZP1XB6V5T
             rank_01JBM30YQ7X3WQAR6HF8C2Q9T8

ULIDs are:
  - 26 chars, Crockford base32, URL-safe
  - Time-ordered (first 48 bits = ms since epoch)
  - Lexicographically sortable (sort == time order)
  - Globally unique without a coordinator

See DATA_ARCHITECTURE.md §4 for the canonical hierarchy that uses these.
"""

from __future__ import annotations

from typing import Literal

from ulid import ULID

# ---------------------------------------------------------------------------
# Prefix registry
# ---------------------------------------------------------------------------
# Canonical entities defined in DATA_ARCHITECTURE.md §5, plus `koi_tick`
# as an event-correlation prefix (ticks are not entities).

Kind = Literal[
    "user",
    "job",
    "koi_tick",
    "plan",
    "rank",
    "event",
    "credentials",
    "gpu_metric",
]

PREFIXES: dict[Kind, str] = {
    "user": "usr",
    "job": "job",
    "koi_tick": "tick",
    "plan": "plan",
    "rank": "rank",
    "event": "evt",
    "credentials": "cred",
    "gpu_metric": "gpum",
}


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


def new_id(kind: Kind) -> str:
    """Generate a prefixed canonical ID for the given entity kind.

    >>> id_ = new_id("job")
    >>> id_.startswith("job_")
    True
    >>> len(id_) == len("job_") + 26
    True
    """
    if kind not in PREFIXES:
        raise ValueError(f"Unknown ID kind: {kind!r}. Add it to PREFIXES first.")
    return f"{PREFIXES[kind]}_{ULID()}"


# Convenience helpers — one per canonical ID kind.


def new_user_id() -> str:
    return new_id("user")


def new_job_id() -> str:
    return new_id("job")


def new_koi_tick_id() -> str:
    # Correlation ID only: ticks are events (tick.started / tick.completed),
    # not entities. There is no koi_ticks table.
    return new_id("koi_tick")


def new_plan_id() -> str:
    return new_id("plan")


def new_rank_id() -> str:
    return new_id("rank")


def new_event_id() -> str:
    return new_id("event")


def new_credentials_ref() -> str:
    return new_id("credentials")


def new_gpu_metric_id() -> str:
    return new_id("gpu_metric")


# ---------------------------------------------------------------------------
# Inspection helpers
# ---------------------------------------------------------------------------


def kind_of(id_: str) -> Kind:
    """Return the canonical kind for an ID string, by prefix.

    Raises ValueError on unknown prefix.
    """
    prefix = id_.split("_", 1)[0]
    for kind, p in PREFIXES.items():
        if p == prefix:
            return kind
    raise ValueError(f"Unknown ID prefix: {prefix!r}")


def is_valid_id(id_: str, kind: Kind | None = None) -> bool:
    """Cheap structural validation.

    Checks the prefix is registered and the ULID body is 26 chars.
    If `kind` is given, also checks the prefix matches that kind.
    """
    try:
        prefix, body = id_.split("_", 1)
    except ValueError:
        return False
    if len(body) != 26:
        return False
    if kind is not None:
        return PREFIXES.get(kind) == prefix
    return prefix in PREFIXES.values()
