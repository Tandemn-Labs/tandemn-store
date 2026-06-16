"""EvidenceStore — Koi tick history in Postgres.

Koi reads the last N FSM ticks before each pass to drive CUSUM/ICP and
surrogate updates. Rows are keyed by ``row_id``; ``user_id`` + ``tick``
are indexed for ``recent()`` queries. Not an Orca handoff surface.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select

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
