"""GpuMetricStore — append-only GPU/inference telemetry in Postgres.

The Orca collector writes one row per (deployment, GPU) per tick; consumers
read recent windows for a deployment. Indexed columns (``deployment_id``,
``gpu_uuid``, ``ts``) back the windowed reads; the 28 metric values live in
``metrics_json``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select

from tandemn_system_data.clients.postgres import PostgresClient
from tandemn_system_data.db.orm import ChainRow, GpuMetricRow, JobRow
from tandemn_system_data.models._base import utc_now
from tandemn_system_data.models.gpu_metric import (
    GpuMetric,
    gpu_metric_from_row,
    gpu_metric_to_metrics,
)


def _to_row(metric: GpuMetric) -> GpuMetricRow:
    return GpuMetricRow(
        metric_id=metric.metric_id,
        ts=metric.ts,
        deployment_id=metric.deployment_id,
        gpu_uuid=metric.gpu_uuid,
        rank_id=metric.rank_id,
        chain_id=metric.chain_id,
        local_rank=metric.local_rank,
        role=metric.role,
        node_name=metric.node_name,
        instance_type=metric.instance_type,
        model_name=metric.model_name,
        metrics_json=gpu_metric_to_metrics(metric),
        created_at=utc_now(),
    )


def _to_model(row: GpuMetricRow) -> GpuMetric:
    return gpu_metric_from_row(
        metric_id=row.metric_id,
        ts=row.ts,
        deployment_id=row.deployment_id,
        gpu_uuid=row.gpu_uuid,
        rank_id=row.rank_id,
        chain_id=row.chain_id,
        local_rank=row.local_rank,
        role=row.role,
        node_name=row.node_name,
        instance_type=row.instance_type,
        model_name=row.model_name,
        metrics=row.metrics_json,
    )


class GpuMetricStore:
    def __init__(self, client: PostgresClient) -> None:
        self._client = client

    def put(self, metric: GpuMetric) -> GpuMetric:
        with self._client.begin() as s:
            s.add(_to_row(metric))
        return metric

    def put_many(self, metrics: Iterable[GpuMetric]) -> list[GpuMetric]:
        materialized = list(metrics)
        if not materialized:
            return []
        with self._client.begin() as s:
            s.add_all(_to_row(m) for m in materialized)
        return materialized

    def get(self, metric_id: str) -> GpuMetric | None:
        with self._client.session() as s:
            row = s.get(GpuMetricRow, metric_id)
            return _to_model(row) if row else None

    def recent(self, deployment_id: str, *, limit: int = 100) -> list[GpuMetric]:
        """Most recent samples for a deployment, newest first."""
        if limit <= 0:
            return []
        with self._client.session() as s:
            rows = s.scalars(
                select(GpuMetricRow)
                .where(GpuMetricRow.deployment_id == deployment_id)
                .order_by(GpuMetricRow.ts.desc())
                .limit(limit)
            ).all()
        return [_to_model(r) for r in rows]

    def rows_for_rank(
        self, deployment_id: str, rank_id: str, *, limit: int = 100
    ) -> list[GpuMetric]:
        """Most recent samples for one ladder rank (across its chains/GPUs).

        rank_id ("{role}-{ladder index}") is only unique within a deployment,
        hence the deployment_id scope. Rows are per-GPU: inference metrics are
        chain-scoped and repeat on every GPU of a TP>1 chain, so aggregate
        them per distinct chain_id, not per row; GPU hardware metrics are
        genuinely per-row.
        """
        if limit <= 0:
            return []
        with self._client.session() as s:
            rows = s.scalars(
                select(GpuMetricRow)
                .where(
                    GpuMetricRow.deployment_id == deployment_id,
                    GpuMetricRow.rank_id == rank_id,
                )
                .order_by(GpuMetricRow.ts.desc())
                .limit(limit)
            ).all()
        return [_to_model(r) for r in rows]

    def rows_for_role(self, deployment_id: str, role: str, *, limit: int = 100) -> list[GpuMetric]:
        """Most recent samples for one PD role ("prefill"/"decode") of a deployment."""
        if limit <= 0:
            return []
        with self._client.session() as s:
            rows = s.scalars(
                select(GpuMetricRow)
                .where(
                    GpuMetricRow.deployment_id == deployment_id,
                    GpuMetricRow.role == role,
                )
                .order_by(GpuMetricRow.ts.desc())
                .limit(limit)
            ).all()
        return [_to_model(r) for r in rows]

    def rows_for_chain(self, chain_id: str, *, limit: int = 100) -> list[GpuMetric]:
        """Most recent samples for one chain (across its GPUs), newest first."""
        if limit <= 0:
            return []
        with self._client.session() as s:
            rows = s.scalars(
                select(GpuMetricRow)
                .where(GpuMetricRow.chain_id == chain_id)
                .order_by(GpuMetricRow.ts.desc())
                .limit(limit)
            ).all()
        return [_to_model(r) for r in rows]

    def rows_in_window(self, deployment_id: str, start: datetime, end: datetime) -> list[GpuMetric]:
        """Samples for a deployment with ts in the inclusive [start, end] window."""
        with self._client.session() as s:
            rows = s.scalars(
                select(GpuMetricRow)
                .where(
                    GpuMetricRow.deployment_id == deployment_id,
                    GpuMetricRow.ts >= start,
                    GpuMetricRow.ts <= end,
                )
                .order_by(GpuMetricRow.ts)
            ).all()
        return [_to_model(r) for r in rows]

    def rows_for_job_window(
        self, user_id: str, job_id: str, start: datetime, end: datetime
    ) -> list[GpuMetric]:
        """Koi read path: telemetry for one user's job in a timestamp window."""
        return self._koi_window(user_id, job_id, start, end)

    def rows_for_rank_window(
        self, user_id: str, job_id: str, rank_id: str, start: datetime, end: datetime
    ) -> list[GpuMetric]:
        """Koi read path: telemetry for one rank in a timestamp window."""
        return self._koi_window(user_id, job_id, start, end, rank_id=rank_id)

    def _koi_window(
        self,
        user_id: str,
        job_id: str,
        start: datetime,
        end: datetime,
        *,
        rank_id: str | None = None,
    ) -> list[GpuMetric]:
        stmt = (
            select(GpuMetricRow)
            .join(ChainRow, GpuMetricRow.chain_id == ChainRow.chain_id)
            .join(JobRow, ChainRow.job_id == JobRow.job_id)
            .where(
                JobRow.user_id == user_id,
                ChainRow.job_id == job_id,
                GpuMetricRow.chain_id.is_not(None),
                GpuMetricRow.rank_id.is_not(None),
                GpuMetricRow.ts >= start,
                GpuMetricRow.ts <= end,
            )
        )
        if rank_id is not None:
            stmt = stmt.where(GpuMetricRow.rank_id == rank_id)
        with self._client.session() as s:
            rows = s.scalars(stmt.order_by(GpuMetricRow.ts)).all()
        return [_to_model(r) for r in rows]
