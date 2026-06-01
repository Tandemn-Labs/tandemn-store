"""Canonical prefixed ID generator.

ID format:  <prefix>_<26-char Crockford-base32 ULID>
Examples:   job_01JBM2YQYZ1KQ9C8GZP1XB6V5T
            alt_01JBM30YQ7X3WQAR6HF8C2Q9T8

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
# Canonical entities defined in DATA_ARCHITECTURE.md §5 plus the `theory`
# prefix reserved for the deferred Vector DB work in §11. Reserving the
# prefix now avoids a future schema migration when theories become real.

Kind = Literal[
    "user",
    "resource_map",
    "job",
    "plan",
    "placement_alternative",
    "chain",
    "chunk",
    "attempt",
    "event",
    "outcome",
    "credentials",
    "theory",  # reserved; not used in MVP
]

PREFIXES: dict[Kind, str] = {
    "user": "usr",
    "resource_map": "rmap",
    "job": "job",
    "plan": "plan",
    "placement_alternative": "alt",
    "chain": "chain",
    "chunk": "chunk",
    "attempt": "att",
    "event": "evt",
    "outcome": "out",
    "credentials": "cred",
    "theory": "thry",
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


# Convenience helpers — one per entity that has a Pydantic/ORM model in MVP.
# `theory` is intentionally omitted; it is reserved-prefix-only for now.


def new_user_id() -> str:
    return new_id("user")


def new_resource_map_id() -> str:
    return new_id("resource_map")


def new_job_id() -> str:
    return new_id("job")


def new_plan_id() -> str:
    return new_id("plan")


def new_placement_alternative_id() -> str:
    return new_id("placement_alternative")


def new_chain_id() -> str:
    return new_id("chain")


def new_chunk_id() -> str:
    return new_id("chunk")


def new_attempt_id() -> str:
    return new_id("attempt")


def new_event_id() -> str:
    return new_id("event")


def new_outcome_id() -> str:
    return new_id("outcome")


def new_credentials_ref() -> str:
    return new_id("credentials")


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
