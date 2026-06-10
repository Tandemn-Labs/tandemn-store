"""Integration tests for JobStore: Orca's job writes and Koi's tick reads.

Requires Postgres (`make up`).
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tandemn_system_data.clients import JobStore, PostgresClient
from tandemn_system_data.db import (
    Base,
    ChainRow,
    PlanJobRow,
    PlanRow,
    RankRow,
    UserRow,
)
from tandemn_system_data.ids import (
    new_chain_id,
    new_plan_id,
    new_rank_id,
    new_user_id,
)
from tandemn_system_data.models import Job, JobKind, JobStatus

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def pg_client() -> PostgresClient:
    return PostgresClient()


@pytest.fixture(scope="module", autouse=True)
def _reset_schema(pg_client: PostgresClient):
    Base.metadata.drop_all(pg_client.engine)
    with pg_client.engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    repo_root = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    yield


@pytest.fixture
def store(pg_client: PostgresClient) -> JobStore:
    return JobStore(pg_client)


@pytest.fixture
def user_id(pg_client: PostgresClient) -> str:
    uid = new_user_id()
    with pg_client.begin() as s:
        s.add(UserRow(user_id=uid, name="job-store-test", created_at=datetime.now(UTC)))
    return uid


def _submit(store: JobStore, user_id: str) -> Job:
    return store.submit(Job(user_id=user_id, kind=JobKind.BATCH))


# ----- writes ---------------------------------------------------------------


def test_submit_and_get(store: JobStore, user_id: str):
    job = _submit(store, user_id)
    fetched = store.get(job.job_id)
    assert fetched is not None
    assert fetched.status is JobStatus.SUBMITTED
    assert fetched.user_id == user_id


def test_get_missing_returns_none(store: JobStore):
    assert store.get("job_does_not_exist") is None


def test_transition_cas_succeeds_then_blocks(store: JobStore, user_id: str):
    job = _submit(store, user_id)

    assert store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.SUBMITTED]) is True
    # Same CAS again must fail: status is no longer 'submitted'.
    assert store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.SUBMITTED]) is False
    assert store.get(job.job_id).status is JobStatus.RUNNING


def test_transition_to_terminal_sets_completed_at(store: JobStore, user_id: str):
    job = _submit(store, user_id)
    store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.SUBMITTED])
    assert store.transition(job.job_id, JobStatus.COMPLETED, [JobStatus.RUNNING]) is True

    done = store.get(job.job_id)
    assert done.status is JobStatus.COMPLETED
    assert done.completed_at is not None


def test_transition_missing_job_returns_false(store: JobStore):
    assert store.transition("job_nope", JobStatus.RUNNING, [JobStatus.SUBMITTED]) is False


# ----- reads (the Koi tick) -------------------------------------------------


def test_waiting_jobs_only_submitted_ordered(store: JobStore, user_id: str):
    first = _submit(store, user_id)
    second = _submit(store, user_id)
    moved = _submit(store, user_id)
    store.transition(moved.job_id, JobStatus.RUNNING, [JobStatus.SUBMITTED])

    waiting = store.waiting_jobs(user_id)
    assert [j.job_id for j in waiting] == [first.job_id, second.job_id]


def test_running_jobs_include_launching_and_active_chains(
    store: JobStore, pg_client: PostgresClient, user_id: str
):
    """Two jobs admitted to one plan share the plan's active chains;
    terminal chains are excluded; launching jobs count as running."""
    now = datetime.now(UTC)
    job_a = _submit(store, user_id)
    job_b = _submit(store, user_id)
    store.transition(job_a.job_id, JobStatus.RUNNING, [JobStatus.SUBMITTED])
    store.transition(job_b.job_id, JobStatus.LAUNCHING, [JobStatus.SUBMITTED])

    plan_id, rank_id = new_plan_id(), new_rank_id()
    running_chain, failed_chain = new_chain_id(), new_chain_id()
    with pg_client.begin() as s:
        s.add(PlanRow(plan_id=plan_id, user_id=user_id, status="executing", created_at=now))
        s.flush()
        for jid in (job_a.job_id, job_b.job_id):
            s.add(
                PlanJobRow(
                    plan_id=plan_id, job_id=jid, priority=0, status="admitted", admitted_at=now
                )
            )
        s.add(
            RankRow(
                plan_id=plan_id,
                rank_id=rank_id,
                rank_index=0,
                strategy="aggregate",
                status="started",
                created_at=now,
            )
        )
        s.flush()
        s.add(
            ChainRow(
                chain_id=running_chain,
                rank_id=rank_id,
                role="aggregate",
                shape_json={"gpu": "H100", "count": 8},
                status="running",
                target_node="node-1",
                created_at=now,
            )
        )
        s.add(
            ChainRow(
                chain_id=failed_chain,
                rank_id=rank_id,
                role="aggregate",
                status="failed",
                created_at=now,
            )
        )

    running = store.running_jobs(user_id)
    assert {r.job.job_id for r in running} == {job_a.job_id, job_b.job_id}

    for r in running:
        assert [c.chain_id for c in r.chains] == [running_chain]  # failed chain excluded
        assert r.chains[0].plan_id == plan_id
        assert r.chains[0].shape_json == {"gpu": "H100", "count": 8}
        assert r.chains[0].target_node == "node-1"


def test_running_job_with_no_plan_has_empty_chains(store: JobStore, user_id: str):
    job = _submit(store, user_id)
    store.transition(job.job_id, JobStatus.LAUNCHING, [JobStatus.SUBMITTED])

    running = store.running_jobs(user_id)
    mine = next(r for r in running if r.job.job_id == job.job_id)
    assert mine.chains == []
