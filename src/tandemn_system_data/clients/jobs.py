"""JobStore — canonical job lifecycle (Orca writes) and the Koi tick
read path (waiting / running jobs with the resources serving them).

Status semantics for the scheduler:

  waiting        status == waiting (new jobs start here until a plan
                 action places them; defer keeps them here)
  running        status == running
  paused         status == paused (preempted; chains torn down)
  active chains  chain.status in {launching, running}

Concurrency: transition() is a compare-and-set
(UPDATE ... WHERE status IN expected), so concurrent writers cannot
clobber a terminal state or double-fire a transition. Reads run inside
one transaction for a consistent snapshot.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select, update

from tandemn_system_data.clients.postgres import PostgresClient
from tandemn_system_data.db.orm import ChainRow, JobRow
from tandemn_system_data.models._base import utc_now
from tandemn_system_data.models.chain import Chain
from tandemn_system_data.models.enums import ChainRole, ChainStatus, JobStatus
from tandemn_system_data.models.job import ChainAllocation, Job, RunningJob

ACTIVE_CHAIN_STATUSES: tuple[ChainStatus, ...] = (
    ChainStatus.LAUNCHING,
    ChainStatus.RUNNING,
)


def _require_shape_count(chain: Chain) -> None:
    """Every launched chain must declare its GPU count in shape_json.

    Capacity accounting (free = total - GPUs used by running chains) reads
    ``shape_json["count"]`` directly; there is no parallelism-derived
    fallback, so a missing or non-positive count is rejected at launch.
    """
    count = chain.shape_json.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise ValueError(
            f"chain {chain.chain_id} shape_json must include a positive int 'count'; got {count!r}"
        )


class JobStore:
    """One instance per process, sharing the caller's PostgresClient."""

    def __init__(self, client: PostgresClient) -> None:
        self._client = client

    # ----- writes (Orca) ---------------------------------------------------

    def submit(self, job: Job) -> Job:
        with self._client.begin() as s:
            s.add(JobRow(**job.model_dump()))
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

    # ----- chains (Orca applies plan actions) ------------------------------

    def launch_chains(self, chains: list[Chain]) -> list[Chain]:
        """Gang launch: insert every chain of a placement in one
        transaction (all or nothing).

        Each chain's shape_json must declare a positive int ``count`` (GPUs
        for that chain); the whole gang is rejected if any chain omits it.
        """
        for chain in chains:
            _require_shape_count(chain)
        with self._client.begin() as s:
            for chain in chains:
                s.add(ChainRow(**chain.model_dump()))
        return chains

    def set_chain_status(
        self,
        chain_id: str,
        to: ChainStatus,
        expected: Iterable[ChainStatus],
    ) -> bool:
        """Compare-and-set chain status change, same semantics as
        transition()."""
        with self._client.begin() as s:
            result = s.execute(
                update(ChainRow)
                .where(ChainRow.chain_id == chain_id, ChainRow.status.in_(list(expected)))
                .values(status=to)
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

    def chains(self, job_id: str) -> list[Chain]:
        """Every chain recorded for a job, newest first."""
        with self._client.session() as s:
            rows = s.scalars(
                select(ChainRow)
                .where(ChainRow.job_id == job_id)
                .order_by(ChainRow.created_at.desc(), ChainRow.chain_id)
            ).all()
            return [Chain.model_validate(r) for r in rows]

    def active_chains(self, job_id: str) -> list[Chain]:
        """The job's launching/running chains, oldest first.

        Telemetry uses this to map worker pods onto canonical chain ids.
        """
        with self._client.session() as s:
            rows = s.scalars(
                select(ChainRow)
                .where(
                    ChainRow.job_id == job_id,
                    ChainRow.status.in_(ACTIVE_CHAIN_STATUSES),
                )
                .order_by(ChainRow.created_at, ChainRow.chain_id)
            ).all()
            return [Chain.model_validate(r) for r in rows]

    def waiting_jobs(self, user_id: str) -> list[Job]:
        return self._jobs_with_status(user_id, JobStatus.WAITING)

    def paused_jobs(self, user_id: str) -> list[Job]:
        return self._jobs_with_status(user_id, JobStatus.PAUSED)

    def running_jobs(self, user_id: str) -> list[RunningJob]:
        """Running jobs plus the active chains serving them."""
        with self._client.session() as s:
            job_rows = s.scalars(
                select(JobRow)
                .where(JobRow.user_id == user_id, JobRow.status == JobStatus.RUNNING)
                .order_by(JobRow.created_at)
            ).all()
            if not job_rows:
                return []

            chain_rows = s.scalars(
                select(ChainRow)
                .where(
                    ChainRow.job_id.in_([r.job_id for r in job_rows]),
                    ChainRow.status.in_(ACTIVE_CHAIN_STATUSES),
                )
                .order_by(ChainRow.created_at)
            ).all()

            chains_by_job: dict[str, list[ChainAllocation]] = {}
            for chain in chain_rows:
                chains_by_job.setdefault(chain.job_id, []).append(
                    ChainAllocation(
                        chain_id=chain.chain_id,
                        plan_id=chain.plan_id,
                        role=ChainRole(chain.role),
                        status=ChainStatus(chain.status),
                        shape_json=chain.shape_json,
                        target_node=chain.target_node,
                    )
                )

            return [
                RunningJob(job=Job.model_validate(r), chains=chains_by_job.get(r.job_id, []))
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
