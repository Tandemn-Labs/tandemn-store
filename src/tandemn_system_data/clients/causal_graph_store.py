"""CausalGraphStore — Koi causal topology and Beta confidence in Postgres.

Koi loads nodes, edges, mechanisms, and confidence metadata at boot,
mutates in memory during a tick (``ConfidenceService`` in S3), and syncs
back via ``sync_edge_metadata`` / ``sync_mechanisms``. Not an Orca
handoff surface.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, select, update

from tandemn_system_data.clients.postgres import PostgresClient
from tandemn_system_data.db.orm import (
    KoiCausalEdgeRow,
    KoiCausalMechanismRow,
    KoiCausalNodeRow,
)
from tandemn_system_data.models.causal_graph import (
    CausalEdge,
    CausalMechanism,
    CausalNode,
    EdgeMetadata,
    MechanismMetadata,
    envs_seen_from_json,
    envs_seen_to_json,
)

_DEFAULT_Q = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}


def _node_to_row(user_id: str, node: CausalNode) -> KoiCausalNodeRow:
    return KoiCausalNodeRow(
        user_id=user_id,
        node_id=node.node_id,
        node_type=node.node_type,
        description=node.description,
        unit=node.unit,
    )


def _node_from_row(row: KoiCausalNodeRow) -> CausalNode:
    return CausalNode(
        node_id=row.node_id,
        node_type=row.node_type,
        description=row.description,
        unit=row.unit,
    )


def _edge_to_row(user_id: str, edge: CausalEdge, metadata: EdgeMetadata) -> KoiCausalEdgeRow:
    return KoiCausalEdgeRow(
        user_id=user_id,
        edge_id=edge.edge_id,
        src=edge.src,
        dst=edge.dst,
        src_type=edge.src_type,
        dst_type=edge.dst_type,
        status=edge.status,
        alpha=metadata.alpha,
        beta=metadata.beta,
        visit_count=metadata.visit_count,
        last_touched_tick=metadata.last_touched_tick,
        q_histogram_json=dict(metadata.q_histogram),
        envs_seen_json=envs_seen_to_json(metadata.envs_seen),
        q3_frequency=metadata.q3_frequency,
    )


def _edge_from_row(row: KoiCausalEdgeRow) -> tuple[CausalEdge, EdgeMetadata]:
    edge = CausalEdge(
        edge_id=row.edge_id,
        src=row.src,
        dst=row.dst,
        src_type=row.src_type,
        dst_type=row.dst_type,
        status=row.status,
    )
    metadata = EdgeMetadata(
        edge_id=row.edge_id,
        alpha=row.alpha,
        beta=row.beta,
        visit_count=row.visit_count,
        last_touched_tick=row.last_touched_tick,
        q_histogram=dict(row.q_histogram_json or _DEFAULT_Q),
        envs_seen=envs_seen_from_json(row.envs_seen_json),
        q3_frequency=row.q3_frequency,
    )
    return edge, metadata


def _mechanism_to_row(
    user_id: str,
    mechanism: CausalMechanism,
    metadata: MechanismMetadata,
) -> KoiCausalMechanismRow:
    assert mechanism.mechanism_id is not None
    return KoiCausalMechanismRow(
        user_id=user_id,
        mechanism_id=mechanism.mechanism_id,
        name=mechanism.name,
        edge_ids_json=list(mechanism.edge_ids),
        scope_json=dict(mechanism.scope),
        narrative=mechanism.narrative,
        status=mechanism.status,
        archived_reason=mechanism.archived_reason,
        alpha=metadata.alpha,
        beta=metadata.beta,
        visit_count=metadata.visit_count,
        last_touched_tick=metadata.last_touched_tick,
        q_histogram_json=dict(metadata.q_histogram),
        envs_seen_json=envs_seen_to_json(metadata.envs_seen),
        inspection_count=metadata.inspection_count,
    )


def _mechanism_from_row(row: KoiCausalMechanismRow) -> tuple[CausalMechanism, MechanismMetadata]:
    mechanism = CausalMechanism(
        mechanism_id=row.mechanism_id,
        name=row.name,
        edge_ids=list(row.edge_ids_json or []),
        scope=dict(row.scope_json or {}),
        narrative=row.narrative,
        status=row.status,
        archived_reason=row.archived_reason,
    )
    metadata = MechanismMetadata(
        mechanism_id=row.mechanism_id,
        alpha=row.alpha,
        beta=row.beta,
        visit_count=row.visit_count,
        last_touched_tick=row.last_touched_tick,
        q_histogram=dict(row.q_histogram_json or _DEFAULT_Q),
        envs_seen=envs_seen_from_json(row.envs_seen_json),
        inspection_count=row.inspection_count,
    )
    return mechanism, metadata


class CausalGraphStore:
    """Per-user causal graph tables. Koi reads at boot; syncs after S3."""

    def __init__(self, client: PostgresClient, *, user_id: str) -> None:
        self._client = client
        self._user_id = user_id

    @property
    def user_id(self) -> str:
        return self._user_id

    def load_nodes(self) -> dict[str, CausalNode]:
        with self._client.session() as s:
            rows = s.scalars(
                select(KoiCausalNodeRow).where(KoiCausalNodeRow.user_id == self._user_id)
            ).all()
        return {row.node_id: _node_from_row(row) for row in rows}

    def load_edges(
        self,
    ) -> tuple[dict[str, CausalEdge], dict[str, EdgeMetadata]]:
        with self._client.session() as s:
            rows = s.scalars(
                select(KoiCausalEdgeRow).where(KoiCausalEdgeRow.user_id == self._user_id)
            ).all()
        edge_table: dict[str, CausalEdge] = {}
        metadata_table: dict[str, EdgeMetadata] = {}
        for row in rows:
            edge, metadata = _edge_from_row(row)
            edge_table[edge.edge_id] = edge
            metadata_table[metadata.edge_id] = metadata
        return edge_table, metadata_table

    def load_mechanisms(
        self,
    ) -> tuple[dict[str, CausalMechanism], dict[str, MechanismMetadata]]:
        with self._client.session() as s:
            rows = s.scalars(
                select(KoiCausalMechanismRow).where(KoiCausalMechanismRow.user_id == self._user_id)
            ).all()
        mechanism_table: dict[str, CausalMechanism] = {}
        metadata_table: dict[str, MechanismMetadata] = {}
        for row in rows:
            mechanism, metadata = _mechanism_from_row(row)
            assert mechanism.mechanism_id is not None
            mechanism_table[mechanism.mechanism_id] = mechanism
            metadata_table[metadata.mechanism_id] = metadata
        return mechanism_table, metadata_table

    def replace_nodes(self, nodes: Iterable[CausalNode]) -> None:
        materialized = list(nodes)
        with self._client.begin() as s:
            s.execute(delete(KoiCausalNodeRow).where(KoiCausalNodeRow.user_id == self._user_id))
            for node in materialized:
                s.add(_node_to_row(self._user_id, node))

    def replace_edges(
        self,
        edges: Iterable[CausalEdge],
        metadata: dict[str, EdgeMetadata],
    ) -> None:
        materialized = list(edges)
        with self._client.begin() as s:
            s.execute(delete(KoiCausalEdgeRow).where(KoiCausalEdgeRow.user_id == self._user_id))
            for edge in materialized:
                edge_metadata = metadata[edge.edge_id]
                s.add(_edge_to_row(self._user_id, edge, edge_metadata))

    def sync_edge_metadata(self, metadata: dict[str, EdgeMetadata]) -> None:
        if not metadata:
            return
        with self._client.begin() as s:
            for edge_id, edge_metadata in metadata.items():
                s.execute(
                    update(KoiCausalEdgeRow)
                    .where(
                        KoiCausalEdgeRow.user_id == self._user_id,
                        KoiCausalEdgeRow.edge_id == edge_id,
                    )
                    .values(
                        alpha=edge_metadata.alpha,
                        beta=edge_metadata.beta,
                        visit_count=edge_metadata.visit_count,
                        last_touched_tick=edge_metadata.last_touched_tick,
                        q_histogram_json=dict(edge_metadata.q_histogram),
                        envs_seen_json=envs_seen_to_json(edge_metadata.envs_seen),
                        q3_frequency=edge_metadata.q3_frequency,
                    )
                )

    def put_mechanism(self, mechanism: CausalMechanism, metadata: MechanismMetadata) -> None:
        row = _mechanism_to_row(self._user_id, mechanism, metadata)
        with self._client.begin() as s:
            s.merge(row)

    def sync_mechanisms(
        self,
        mechanisms: dict[str, CausalMechanism],
        metadata: dict[str, MechanismMetadata],
    ) -> None:
        if not mechanisms:
            return
        with self._client.begin() as s:
            for mechanism_id, mechanism in mechanisms.items():
                mechanism_metadata = metadata[mechanism_id]
                s.merge(_mechanism_to_row(self._user_id, mechanism, mechanism_metadata))

    def is_empty(self) -> bool:
        with self._client.session() as s:
            node = s.scalar(
                select(KoiCausalNodeRow.node_id)
                .where(KoiCausalNodeRow.user_id == self._user_id)
                .limit(1)
            )
            return node is None
