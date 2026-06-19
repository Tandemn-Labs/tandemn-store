"""EvidenceStore — Koi tick history in Postgres.

Koi reads the last N FSM ticks before each pass to drive CUSUM/ICP and
surrogate updates. Rows are keyed by ``row_id``; ``user_id`` + ``tick``
are indexed for ``recent()`` queries. Not an Orca handoff surface.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select

from tandemn_system_data.clients.postgres import PostgresClient
from tandemn_system_data.db.orm import EvidenceRowRow
from tandemn_system_data.models.evidence import (
    EvidenceRow,
    evidence_payload_from_row,
    evidence_row_to_payload,
)


def _to_row(user_id: str, row: EvidenceRow) -> EvidenceRowRow:
    from tandemn_system_data.models._base import utc_now

    return EvidenceRowRow(
        row_id=row.row_id,
        user_id=user_id,
        tick=row.tick,
        job_id=row.job_id,
        rank_id=row.rank_id,
        deploy_timestamp_utc=row.deploy_timestamp_utc,
        payload_json=evidence_row_to_payload(row),
        created_at=utc_now(),
    )


def _to_model(db_row: EvidenceRowRow) -> EvidenceRow:
    return evidence_payload_from_row(
        row_id=db_row.row_id,
        tick=db_row.tick,
        deploy_timestamp_utc=db_row.deploy_timestamp_utc,
        job_id=db_row.job_id,
        rank_id=db_row.rank_id,
        payload=db_row.payload_json,
    )


class EvidenceStore:
    def __init__(self, client: PostgresClient) -> None:
        self._client = client

    def put(self, user_id: str, row: EvidenceRow) -> EvidenceRow:
        with self._client.begin() as s:
            s.merge(_to_row(user_id, row))
        return row

    def put_many(self, user_id: str, rows: Iterable[EvidenceRow]) -> list[EvidenceRow]:
        materialized = list(rows)
        if not materialized:
            return []
        with self._client.begin() as s:
            for row in materialized:
                s.merge(_to_row(user_id, row))
        return materialized

    def get(self, row_id: str) -> EvidenceRow | None:
        with self._client.session() as s:
            db_row = s.get(EvidenceRowRow, row_id)
            return _to_model(db_row) if db_row else None

    def recent(self, user_id: str, *, last_n_ticks: int = 10) -> list[EvidenceRow]:
        """All evidence rows for the ``last_n_ticks`` most recent FSM ticks."""
        if last_n_ticks <= 0:
            return []
        with self._client.session() as s:
            tick_ids = list(
                s.scalars(
                    select(EvidenceRowRow.tick)
                    .where(EvidenceRowRow.user_id == user_id)
                    .distinct()
                    .order_by(EvidenceRowRow.tick.desc())
                    .limit(last_n_ticks)
                ).all()
            )
            if not tick_ids:
                return []
            rows = s.scalars(
                select(EvidenceRowRow)
                .where(
                    EvidenceRowRow.user_id == user_id,
                    EvidenceRowRow.tick.in_(tick_ids),
                )
                .order_by(EvidenceRowRow.tick, EvidenceRowRow.job_id, EvidenceRowRow.rank_id)
            ).all()
            return [_to_model(r) for r in rows]

    def current_tick(self, user_id: str) -> int:
        """Latest tick recorded for one user, or 0 when no evidence exists."""
        with self._client.session() as s:
            tick = s.scalar(
                select(func.max(EvidenceRowRow.tick)).where(EvidenceRowRow.user_id == user_id)
            )
        return int(tick or 0)

    def rows_in_window(self, user_id: str, start_tick: int, end_tick: int) -> list[EvidenceRow]:
        """Evidence rows with tick in the inclusive [start_tick, end_tick] window."""
        with self._client.session() as s:
            rows = s.scalars(
                select(EvidenceRowRow)
                .where(
                    EvidenceRowRow.user_id == user_id,
                    EvidenceRowRow.tick >= int(start_tick),
                    EvidenceRowRow.tick <= int(end_tick),
                )
                .order_by(EvidenceRowRow.tick, EvidenceRowRow.job_id, EvidenceRowRow.rank_id)
            ).all()
        return [_to_model(r) for r in rows]

    def rows_for_job(self, user_id: str, job_id: str) -> list[EvidenceRow]:
        with self._client.session() as s:
            rows = s.scalars(
                select(EvidenceRowRow)
                .where(EvidenceRowRow.user_id == user_id, EvidenceRowRow.job_id == job_id)
                .order_by(EvidenceRowRow.tick, EvidenceRowRow.rank_id)
            ).all()
        return [_to_model(r) for r in rows]

    def rows_for_rank(self, user_id: str, job_id: str, rank_id: str) -> list[EvidenceRow]:
        with self._client.session() as s:
            rows = s.scalars(
                select(EvidenceRowRow)
                .where(
                    EvidenceRowRow.user_id == user_id,
                    EvidenceRowRow.job_id == job_id,
                    EvidenceRowRow.rank_id == rank_id,
                )
                .order_by(EvidenceRowRow.tick)
            ).all()
        return [_to_model(r) for r in rows]

    def rows_for_edge(
        self, user_id: str, edge_id: str, limit: int | None = None
    ) -> list[EvidenceRow]:
        rows = [r for r in self._rows_for_user(user_id) if edge_id in self._payload_edges(r)]
        return [_to_model(r) for r in self._apply_limit(rows, limit)]

    def rows_for_mechanism(
        self, user_id: str, mechanism_id: str, limit: int | None = None
    ) -> list[EvidenceRow]:
        rows = [
            r for r in self._rows_for_user(user_id) if mechanism_id in self._payload_mechanisms(r)
        ]
        return [_to_model(r) for r in self._apply_limit(rows, limit)]

    def rows_for_environment(self, user_id: str, env_label: tuple[str, ...]) -> list[EvidenceRow]:
        wanted = [str(part) for part in env_label]
        return [
            _to_model(r)
            for r in self._rows_for_user(user_id)
            if self._payload_env_label(r) == wanted
        ]

    def recently_decided(
        self, user_id: str, window: int, tick: int | None = None
    ) -> list[EvidenceRow]:
        upper = self.current_tick(user_id) if tick is None else int(tick)
        return self.rows_in_window(user_id, max(0, upper - int(window)), upper)

    def retrieve_similar_rows(
        self,
        user_id: str,
        job_features: dict,
        top_k: int = 200,
    ) -> list[EvidenceRow]:
        """Recent rows with matching workload type when available, else latest rows."""
        top_k = int(top_k)
        if top_k <= 0:
            return []
        rows = self._rows_for_user(user_id)
        workload_type = self._workload_type(job_features)
        if workload_type is not None:
            matched = [
                r for r in rows if self._workload_type(self._payload_w_observed(r)) == workload_type
            ]
            if matched:
                rows = matched
        return [_to_model(r) for r in rows[-top_k:]]

    def _rows_for_user(self, user_id: str) -> list[EvidenceRowRow]:
        with self._client.session() as s:
            return list(
                s.scalars(
                    select(EvidenceRowRow)
                    .where(EvidenceRowRow.user_id == user_id)
                    .order_by(EvidenceRowRow.tick, EvidenceRowRow.job_id, EvidenceRowRow.rank_id)
                ).all()
            )

    @staticmethod
    def _apply_limit(rows: list[EvidenceRowRow], limit: int | None) -> list[EvidenceRowRow]:
        return rows[-int(limit) :] if limit is not None else rows

    @staticmethod
    def _payload_edges(row: EvidenceRowRow) -> dict:
        return row.payload_json.get("icp_result_per_edge") or {}

    @staticmethod
    def _payload_mechanisms(row: EvidenceRowRow) -> list:
        return list(row.payload_json.get("mechanism_ids") or [])

    @staticmethod
    def _payload_env_label(row: EvidenceRowRow) -> list:
        return list(row.payload_json.get("env_label") or [])

    @staticmethod
    def _payload_w_observed(row: EvidenceRowRow) -> dict:
        return dict(row.payload_json.get("W_observed") or {})

    @staticmethod
    def _workload_type(features: dict | None) -> str | None:
        if not features:
            return None
        value = features.get("type") or features.get("workload_type")
        return str(value).lower() if value is not None else None
