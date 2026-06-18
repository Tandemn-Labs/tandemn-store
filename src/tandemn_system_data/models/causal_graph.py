"""Koi causal graph — nodes, edges, mechanisms, and Beta confidence state.

Persisted via ``CausalGraphStore`` (Postgres ``koi_causal_*`` tables). Koi
loads topology and confidence at boot, mutates in memory during a tick, and
syncs metadata back after S3. Not an Orca handoff surface.

``edge_id`` convention: ``"{src}->{dst}"``. ``mechanism_id`` is a stable
hash over sorted ``edge_ids`` + ``scope`` (see intelligence
``MechanismRegistry.make_mechanism_id``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tandemn_system_data.models.evidence import EnvLabel

_DEFAULT_Q_HISTOGRAM: dict[str, int] = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}


def envs_seen_to_json(envs: set[EnvLabel]) -> list[list[str]]:
    return [list(env) for env in sorted(envs)]


def envs_seen_from_json(raw: Any) -> set[EnvLabel]:
    if not raw:
        return set()
    result: set[EnvLabel] = set()
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) >= 5:
            result.add((str(item[0]), str(item[1]), str(item[2]), str(item[3]), str(item[4])))
    return result


@dataclass
class CausalNode:
    node_id: str
    node_type: str
    description: str | None = None
    unit: str | None = None


@dataclass
class CausalEdge:
    edge_id: str
    src: str
    dst: str
    src_type: str
    dst_type: str
    status: str = "active"


@dataclass
class EdgeMetadata:
    edge_id: str
    alpha: float = 1.0
    beta: float = 1.0
    visit_count: int = 0
    last_touched_tick: int | None = None
    q_histogram: dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_Q_HISTOGRAM))
    envs_seen: set[EnvLabel] = field(default_factory=set)
    q3_frequency: float = 0.0


@dataclass
class CausalMechanism:
    edge_ids: list[str]
    scope: dict[str, Any]
    narrative: str
    name: str = ""
    status: str = "active"
    mechanism_id: str | None = None
    archived_reason: str | None = None


@dataclass
class MechanismMetadata:
    mechanism_id: str
    alpha: float = 1.0
    beta: float = 1.0
    visit_count: int = 0
    envs_seen: set[EnvLabel] = field(default_factory=set)
    last_touched_tick: int | None = None
    q_histogram: dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_Q_HISTOGRAM))
    inspection_count: int = 0
