"""JobStore — canonical job lifecycle (Orca writes) and the Koi tick
read path (waiting / running jobs with the resources serving them).

Status semantics for the scheduler:

  waiting        status == waiting (new jobs start here until a plan
                 action places them; defer keeps them here)
  running        status == running
  paused         status == paused (preempted; ranks torn down)
  active ranks   rank.status in {launching, running}

Concurrency: transition() is a compare-and-set
(UPDATE ... WHERE status IN expected), so concurrent writers cannot
clobber a terminal state or double-fire a transition. Reads run inside
one transaction for a consistent snapshot.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from tandemn_system_data.clients.postgres import PostgresClient
from tandemn_system_data.db.orm import EventRow, JobRow, RankRow
from tandemn_system_data.events import JobSubmittedPayload
from tandemn_system_data.models._base import utc_now
from tandemn_system_data.models.enums import JobStatus, RankRole, RankStatus
from tandemn_system_data.models.event import Event
from tandemn_system_data.models.job import Job, RankAllocation, RunningJob
from tandemn_system_data.models.rank import Rank

ACTIVE_RANK_STATUSES: tuple[RankStatus, ...] = (
    RankStatus.LAUNCHING,
    RankStatus.RUNNING,
)


class JobStore:
    """One instance per process, sharing the caller's PostgresClient."""

    def __init__(self, client: PostgresClient) -> None:
        self._client = client

    # ----- writes (Orca) ---------------------------------------------------

    def submit(self, job: Job) -> Job:
        event = Event(
            user_id=job.user_id,
            job_id=job.job_id,
            type="job.submitted",
            payload_json=JobSubmittedPayload(
                job_id=job.job_id,
                user_id=job.user_id,
            ).model_dump(mode="json"),
            created_at=job.created_at,
        )
        with self._client.begin() as s:
            s.add(JobRow(**job.model_dump()))
            s.add(
                EventRow(
                    event_id=event.event_id,
                    user_id=event.user_id,
                    job_id=event.job_id,
                    rank_id=event.rank_id,
                    type=event.type,
                    payload_json=event.payload_json,
                    created_at=event.created_at,
                )
            )
        return job

    def transition(
        self,
        job_id: str,
        to: JobStatus,
        expected: Iterable[JobStatus],
        *,
        finish_reason: str | None = None,
    ) -> bool:
        """Compare-and-set status change. Returns False (no write) when the
        job is missing or its current status is not in `expected`.

        finish_reason is only meaningful with to=FINISHED: None means
        success, a reason code (FAILED, CANCELLED, ...) means failure.
        """
        values: dict = {"status": to}
        if to is JobStatus.RUNNING:
            values["error_message"] = None
        if to is JobStatus.FINISHED:
            values["finished_at"] = utc_now()
            values["finish_reason"] = finish_reason
        with self._client.begin() as s:
            result = s.execute(
                update(JobRow)
                .where(JobRow.job_id == job_id, JobRow.status.in_(list(expected)))
                .values(**values)
            )
            # Session.execute(update()) always returns a CursorResult.
            return result.rowcount == 1  # type: ignore[attr-defined]

    def fail(
        self,
        job_id: str,
        expected: Iterable[JobStatus],
        *,
        finish_reason: str,
        error_message: str,
    ) -> bool:
        """Atomically finish a job with a user-visible failure detail."""
        with self._client.begin() as s:
            result = s.execute(
                update(JobRow)
                .where(JobRow.job_id == job_id, JobRow.status.in_(list(expected)))
                .values(
                    status=JobStatus.FINISHED,
                    finish_reason=finish_reason,
                    error_message=error_message,
                    finished_at=utc_now(),
                )
            )
            return result.rowcount == 1  # type: ignore[attr-defined]

    def set_error(self, job_id: str, error_message: str | None) -> bool:
        """Set or clear the latest deployment error without changing job state."""
        with self._client.begin() as s:
            result = s.execute(
                update(JobRow).where(JobRow.job_id == job_id).values(error_message=error_message)
            )
            return result.rowcount == 1  # type: ignore[attr-defined]

    # ----- ranks (Orca applies plan actions) -------------------------------

    def launch_ranks(self, ranks: list[Rank]) -> list[Rank]:
        """Atomically insert or refresh ranks without changing their owning job."""
        with self._client.begin() as s:
            for rank in ranks:
                stmt = insert(RankRow).values(**rank.model_dump())
                persisted_rank_id = s.scalar(
                    stmt.on_conflict_do_update(
                        index_elements=[RankRow.rank_id],
                        set_={
                            "job_id": stmt.excluded.job_id,
                            "plan_id": stmt.excluded.plan_id,
                            "role": stmt.excluded.role,
                            "shape_json": stmt.excluded.shape_json,
                            "n_replicas": stmt.excluded.n_replicas,
                            "status": stmt.excluded.status,
                            "reason_code": stmt.excluded.reason_code,
                            "updated_at": stmt.excluded.updated_at,
                        },
                        where=RankRow.job_id == stmt.excluded.job_id,
                    ).returning(RankRow.rank_id)
                )
                if persisted_rank_id is None:
                    raise ValueError(f"rank {rank.rank_id} already belongs to another job")
        return ranks

    def set_rank_status(
        self,
        rank_id: str,
        to: RankStatus,
        expected: Iterable[RankStatus],
        *,
        reason_code: str | None = None,
    ) -> bool:
        """Compare-and-set rank status change, with failure provenance."""
        with self._client.begin() as s:
            result = s.execute(
                update(RankRow)
                .where(RankRow.rank_id == rank_id, RankRow.status.in_(list(expected)))
                .values(status=to, reason_code=reason_code, updated_at=utc_now())
            )
            return result.rowcount == 1  # type: ignore[attr-defined]

    # ----- reads (Koi tick + lookups) --------------------------------------

    def get(self, job_id: str) -> Job | None:
        with self._client.session() as s:
            row = s.get(JobRow, job_id)
            return Job.model_validate(row) if row else None

    def list_jobs(self, user_id: str, *, limit: int = 200) -> list[Job]:
        """The user's newest jobs across every lifecycle state."""
        if limit <= 0:
            return []
        with self._client.session() as s:
            rows = s.scalars(
                select(JobRow)
                .where(JobRow.user_id == user_id)
                .order_by(JobRow.created_at.desc())
                .limit(limit)
            ).all()
            return [Job.model_validate(r) for r in rows]

    def ranks(self, job_id: str) -> list[Rank]:
        """Every rank recorded for a job, newest first."""
        with self._client.session() as s:
            rows = s.scalars(
                select(RankRow)
                .where(RankRow.job_id == job_id)
                .order_by(RankRow.created_at.desc(), RankRow.rank_id)
            ).all()
            return [Rank.model_validate(r) for r in rows]

    def failed_ranks_since(self, job_id: str, since: datetime) -> list[Rank]:
        """Rank failures for a job since a timestamp, newest first."""
        with self._client.session() as s:
            rows = s.scalars(
                select(RankRow)
                .where(
                    RankRow.job_id == job_id,
                    RankRow.status == RankStatus.FAILED,
                    RankRow.updated_at >= since,
                )
                .order_by(RankRow.updated_at.desc(), RankRow.rank_id)
            ).all()
            return [Rank.model_validate(r) for r in rows]

    def active_ranks(self, job_id: str) -> list[Rank]:
        """The job's launching/running ranks, oldest first."""
        with self._client.session() as s:
            rows = s.scalars(
                select(RankRow)
                .where(
                    RankRow.job_id == job_id,
                    RankRow.status.in_(ACTIVE_RANK_STATUSES),
                )
                .order_by(RankRow.created_at, RankRow.rank_id)
            ).all()
            return [Rank.model_validate(r) for r in rows]

    def waiting_jobs(self, user_id: str) -> list[Job]:
        return self._jobs_with_status(user_id, JobStatus.WAITING)

    def paused_jobs(self, user_id: str) -> list[Job]:
        return self._jobs_with_status(user_id, JobStatus.PAUSED)

    def running_jobs(self, user_id: str) -> list[RunningJob]:
        """Running jobs plus the active ranks serving them."""
        with self._client.session() as s:
            job_rows = s.scalars(
                select(JobRow)
                .where(JobRow.user_id == user_id, JobRow.status == JobStatus.RUNNING)
                .order_by(JobRow.created_at)
            ).all()
            if not job_rows:
                return []

            rank_rows = s.scalars(
                select(RankRow)
                .where(
                    RankRow.job_id.in_([r.job_id for r in job_rows]),
                    RankRow.status.in_(ACTIVE_RANK_STATUSES),
                )
                .order_by(RankRow.created_at)
            ).all()

            ranks_by_job: dict[str, list[RankAllocation]] = {}
            for rank in rank_rows:
                ranks_by_job.setdefault(rank.job_id, []).append(
                    RankAllocation(
                        rank_id=rank.rank_id,
                        plan_id=rank.plan_id,
                        role=RankRole(rank.role),
                        status=RankStatus(rank.status),
                        shape_json=rank.shape_json,
                        n_replicas=rank.n_replicas,
                        reason_code=rank.reason_code,
                    )
                )

            return [
                RunningJob(job=Job.model_validate(r), ranks=ranks_by_job.get(r.job_id, []))
                for r in job_rows
            ]

    def _jobs_with_status(self, user_id: str, status: JobStatus) -> list[Job]:
        with self._client.session() as s:
            rows = s.scalars(
                select(JobRow)
                .where(JobRow.user_id == user_id, JobRow.status == status)
                .order_by(JobRow.created_at)
            ).all()
            return [Job.model_validate(r) for r in rows]
