"""Canonical prefixed ID generator.

ID format: <prefix>_<26-char base32 ULID>
Examples: job_01J9..., dec_01J9..., alt_01J9...

Full implementation lands in Phase 1b. Phase 1a stub exists so other
modules can import the function names.
"""

from __future__ import annotations

# Prefix registry. Add new entities here.
PREFIXES = {
    "tenant": "tnt",
    "resource_map": "rmap",
    "job": "job",
    "decision": "dec",
    "plan": "plan",
    "placement_alternative": "alt",
    "chain": "chain",
    "attempt": "att",
    "event": "evt",
    "outcome": "out",
    "theory": "thry",
    "credentials": "cred",
}


def new_id(kind: str) -> str:
    """Generate a prefixed canonical ID. Phase 1a stub."""
    raise NotImplementedError("ID generator lands in Phase 1b")
