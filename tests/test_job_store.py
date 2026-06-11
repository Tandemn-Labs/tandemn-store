"""Integration tests for JobStore: Orca's job writes and Koi's tick reads.

Requires Postgres (`make up`).
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tandemn_system_data.clients import JobStore, PostgresClient
from tandemn_system_data.db import Base, ChainRow, PlanRow, UserRow
from tandemn_system_data.ids import new_chain_id, new_plan_id, new_user_id
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
    assert fetched.status is JobStatus.WAITING
    assert fetched.user_id == user_id


def test_get_missing_returns_none(store: JobStore):
    assert store.get("job_does_not_exist") is None


def test_transition_cas_succeeds_then_blocks(store: JobStore, user_id: str):
    job = _submit(store, user_id)

    # place: waiting -> running
    assert store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.WAITING]) is True
    # Same CAS again must fail: status is no longer 'waiting'.
    assert store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.WAITING]) is False
    assert store.get(job.job_id).status is JobStatus.RUNNING


def test_preempt_and_resume_cycle(store: JobStore, user_id: str):
    job = _submit(store, user_id)
    store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.WAITING])

    # preempt: running -> paused
    assert store.transition(job.job_id, JobStatus.PAUSED, [JobStatus.RUNNING]) is True
    assert store.paused_jobs(user_id)[-1].job_id == job.job_id

    # place again: paused -> running
    assert store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.PAUSED]) is True


def test_finish_success_and_failure(store: JobStore, user_id: str):
    ok = _submit(store, user_id)
    store.transition(ok.job_id, JobStatus.RUNNING, [JobStatus.WAITING])
    assert store.transition(ok.job_id, JobStatus.FINISHED, [JobStatus.RUNNING]) is True
    done = store.get(ok.job_id)
    assert done.status is JobStatus.FINISHED
    assert done.finish_reason is None  # success
    assert done.finished_at is not None

    bad = _submit(store, user_id)
    store.transition(bad.job_id, JobStatus.RUNNING, [JobStatus.WAITING])
    store.transition(bad.job_id, JobStatus.FINISHED, [JobStatus.RUNNING], finish_reason="FAILED")
    assert store.get(bad.job_id).finish_reason == "FAILED"


def test_transition_missing_job_returns_false(store: JobStore):
    assert store.transition("job_nope", JobStatus.RUNNING, [JobStatus.WAITING]) is False


# ----- reads (the Koi tick) -------------------------------------------------


def test_waiting_jobs_only_waiting_ordered(store: JobStore, user_id: str):
    first = _submit(store, user_id)
    second = _submit(store, user_id)
    moved = _submit(store, user_id)
    store.transition(moved.job_id, JobStatus.RUNNING, [JobStatus.WAITING])

    waiting = store.waiting_jobs(user_id)
    assert [j.job_id for j in waiting] == [first.job_id, second.job_id]


def test_running_jobs_carry_their_active_chains(
    store: JobStore, pg_client: PostgresClient, user_id: str
):
    """Chains are job-scoped; failed/stopped chains are excluded."""
    now = datetime.now(UTC)
    job = _submit(store, user_id)
    store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.WAITING])

    plan_id = new_plan_id()
    prefill, decode, dead = new_chain_id(), new_chain_id(), new_chain_id()
    with pg_client.begin() as s:
        s.add(
            PlanRow(
                plan_id=plan_id,
                user_id=user_id,
                tick_rationale="",
                actions_json=[{"job_id": job.job_id, "type": "place"}],
                status="applied",
                created_at=now,
            )
        )
        for chain_id, role, status in (
            (prefill, "prefill", "running"),
            (decode, "decode", "launching"),
            (dead, "decode", "failed"),
        ):
            s.add(
                ChainRow(
                    chain_id=chain_id,
                    job_id=job.job_id,
                    plan_id=plan_id,
                    role=role,
                    shape_json={"gpu": "H100", "count": 8},
                    target_node="node-1",
                    status=status,
                    created_at=now,
                )
            )

    running = store.running_jobs(user_id)
    mine = next(r for r in running if r.job.job_id == job.job_id)
    assert {c.chain_id for c in mine.chains} == {prefill, decode}  # dead excluded
    assert all(c.plan_id == plan_id for c in mine.chains)
    assert mine.chains[0].shape_json == {"gpu": "H100", "count": 8}


def test_running_job_with_no_chains_has_empty_list(store: JobStore, user_id: str):
    job = _submit(store, user_id)
    store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.WAITING])

    running = store.running_jobs(user_id)
    mine = next(r for r in running if r.job.job_id == job.job_id)
    assert mine.chains == []
