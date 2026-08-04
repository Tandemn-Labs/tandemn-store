"""PlanStore — the Koi -> Orca plan handoff.

Koi writes a plan (`create`); Orca polls `unapplied`, applies the
actions (launching ranks, transitioning jobs), and calls
`mark_applied`. mark_applied is a compare-and-set so two Orca workers
cannot apply the same plan twice.
"""

from __future__ import annotations

from sqlalchemy import select, update

from tandemn_system_data.clients.postgres import PostgresClient
from tandemn_system_data.db.orm import PlanRow
from tandemn_system_data.models.plan import Plan, PlanAction

STATUS_CREATED = "created"
STATUS_APPLIED = "applied"


def _to_row(plan: Plan) -> PlanRow:
    return PlanRow(
        plan_id=plan.plan_id,
        user_id=plan.user_id,
        koi_version=plan.koi_version,
        tick_rationale=plan.tick_rationale,
        actions_json=[a.model_dump(mode="json") for a in plan.actions],
        status=plan.status,
        created_at=plan.created_at,
    )


def _to_model(row: PlanRow) -> Plan:
    return Plan(
        plan_id=row.plan_id,
        user_id=row.user_id,
        koi_version=row.koi_version,
        tick_rationale=row.tick_rationale,
        actions=[PlanAction.model_validate(a) for a in row.actions_json],
        status=row.status,
        created_at=row.created_at,
    )


class PlanStore:
    def __init__(self, client: PostgresClient) -> None:
        self._client = client

    def create(self, plan: Plan) -> Plan:
        with self._client.begin() as s:
            s.add(_to_row(plan))
        return plan

    def get(self, plan_id: str) -> Plan | None:
        with self._client.session() as s:
            row = s.get(PlanRow, plan_id)
            return _to_model(row) if row else None

    def list_plans(self, user_id: str, *, limit: int = 200) -> list[Plan]:
        """The user's newest plans across every status."""
        if limit <= 0:
            return []
        with self._client.session() as s:
            rows = s.scalars(
                select(PlanRow)
                .where(PlanRow.user_id == user_id)
                .order_by(PlanRow.created_at.desc())
                .limit(limit)
            ).all()
            return [_to_model(r) for r in rows]

    def unapplied(self, user_id: str) -> list[Plan]:
        """Plans Orca has not acted on yet, oldest first."""
        with self._client.session() as s:
            rows = s.scalars(
                select(PlanRow)
                .where(PlanRow.user_id == user_id, PlanRow.status == STATUS_CREATED)
                .order_by(PlanRow.created_at)
            ).all()
            return [_to_model(r) for r in rows]

    def mark_applied(self, plan_id: str) -> bool:
        """CAS created -> applied. False when missing or already applied."""
        with self._client.begin() as s:
            result = s.execute(
                update(PlanRow)
                .where(PlanRow.plan_id == plan_id, PlanRow.status == STATUS_CREATED)
                .values(status=STATUS_APPLIED)
            )
            return result.rowcount == 1  # type: ignore[attr-defined]
