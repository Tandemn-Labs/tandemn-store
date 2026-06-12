"""Integration: the canonical spine — migrations, hierarchy round-trip,
JobStore, event log. Requires Postgres (`make up`)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect

from tandemn_system_data.clients import JobStore, PostgresClient, PostgresEventLog
from tandemn_system_data.db import ALL_TABLES, ChainRow, EventRow, JobRow, PlanRow, UserRow
from tandemn_system_data.ids import (
    new_chain_id,
    new_event_id,
    new_job_id,
    new_plan_id,
    new_user_id,
)
from tandemn_system_data.models import Event, Job, JobKind, JobStatus
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def _schema(fresh_schema):
    pass


@pytest.fixture
def store(pg_client: PostgresClient) -> JobStore:
    return JobStore(pg_client)


@pytest.fixture
def user_id(pg_client: PostgresClient) -> str:
    uid = new_user_id()
    with pg_client.begin() as s:
        s.add(UserRow(user_id=uid, name="spine-test", created_at=datetime.now(UTC)))
    return uid


# ----- Migrations ------------------------------------------------------------


def test_migration_creates_spine_and_matches_orm(pg_client: PostgresClient):
    db_tables = set(inspect(pg_client.engine).get_table_names())
    assert {row.__tablename__ for row in ALL_TABLES}.issubset(db_tables)

    result = subprocess.run(
        ["uv", "run", "alembic", "check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "No new upgrade operations detected" in (result.stdout + result.stderr)


# ----- Hierarchy round-trip ---------------------------------------------------


def test_full_hierarchy_roundtrip_and_cascades(pg_client: PostgresClient, user_id: str):
    """user -> job -> chains (gang-launched PD pair) + plan + event.
    Deleting the job cascades to chains; the event log survives."""
    now = datetime.now(UTC)
    job_id, plan_id = new_job_id(), new_plan_id()
    prefill_id, decode_id, event_id = new_chain_id(), new_chain_id(), new_event_id()

    with pg_client.begin() as s:
        s.add(
            JobRow(
                job_id=job_id,
                user_id=user_id,
                kind="batch",
                spec_json={"model": "google/gemma-4-31B-it"},
                input_source={"type": "s3", "uri": "s3://ventura/inputs/x.jsonl"},
                output_target={"type": "s3", "uri": "s3://ventura/outputs/"},
                status="waiting",
                created_at=now,
            )
        )
        s.flush()
        s.add(
            PlanRow(
                plan_id=plan_id,
                user_id=user_id,
                tick_rationale="spare capacity; gang-place the PD pair",
                actions_json=[
                    {
                        "job_id": job_id,
                        "type": "place",
                        "ladder": [
                            {"prefill": {"gpu": "H100", "count": 8, "chains": 2}},
                            {"decode": {"gpu": "A100", "count": 8, "chains": 1}},
                        ],
                        "target_tps": 1500,
                    }
                ],
                status="applied",
                created_at=now,
            )
        )
        for chain_id, role, gpu in ((prefill_id, "prefill", "H100"), (decode_id, "decode", "A100")):
            s.add(
                ChainRow(
                    chain_id=chain_id,
                    job_id=job_id,
                    plan_id=plan_id,
                    role=role,
                    shape_json={"gpu": gpu, "count": 8},
                    target_node="gpu-node-1",
                    status="running",
                    created_at=now,
                )
            )
        s.add(
            EventRow(
                event_id=event_id,
                user_id=user_id,
                job_id=job_id,
                chain_id=decode_id,
                type="chain.launched",
                payload_json={"chain_id": decode_id, "job_id": job_id, "role": "decode"},
                created_at=now,
            )
        )

    with pg_client.session() as s:
        plan = s.get(PlanRow, plan_id)
        assert plan.actions_json[0]["ladder"][0]["prefill"]["count"] == 8
        chains = [s.get(ChainRow, prefill_id), s.get(ChainRow, decode_id)]
        assert {c.role for c in chains} == {"prefill", "decode"}
        assert all(c.job_id == job_id and c.plan_id == plan_id for c in chains)

    with pg_client.begin() as s:
        s.delete(s.get(JobRow, job_id))

    with pg_client.session() as s:
        assert s.get(ChainRow, prefill_id) is None  # cascaded
        assert s.get(EventRow, event_id) is not None  # audit log survives


# ----- JobStore ---------------------------------------------------------------


def test_job_lifecycle_with_cas(store: JobStore, user_id: str):
    """waiting -> running -> paused -> running -> finished, all CAS-guarded."""
    job = store.submit(Job(user_id=user_id, kind=JobKind.BATCH))
    assert store.get(job.job_id).status is JobStatus.WAITING

    assert store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.WAITING]) is True
    assert store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.WAITING]) is False  # CAS
    assert store.transition(job.job_id, JobStatus.PAUSED, [JobStatus.RUNNING]) is True
    assert store.paused_jobs(user_id)[-1].job_id == job.job_id
    assert store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.PAUSED]) is True

    assert store.transition(
        job.job_id, JobStatus.FINISHED, [JobStatus.RUNNING], finish_reason="FAILED"
    )
    done = store.get(job.job_id)
    assert done.finish_reason == "FAILED" and done.finished_at is not None

    assert store.transition("job_nope", JobStatus.RUNNING, [JobStatus.WAITING]) is False
    assert store.get("job_nope") is None


def test_koi_reads_waiting_and_running_with_chains(
    store: JobStore, pg_client: PostgresClient, user_id: str
):
    now = datetime.now(UTC)
    waiting = store.submit(Job(user_id=user_id, kind=JobKind.BATCH))
    running = store.submit(Job(user_id=user_id, kind=JobKind.BATCH))
    store.transition(running.job_id, JobStatus.RUNNING, [JobStatus.WAITING])

    live, dead = new_chain_id(), new_chain_id()
    with pg_client.begin() as s:
        for chain_id, status in ((live, "running"), (dead, "failed")):
            s.add(
                ChainRow(
                    chain_id=chain_id,
                    job_id=running.job_id,
                    role="aggregate",
                    shape_json={"gpu": "H100", "count": 8},
                    status=status,
                    created_at=now,
                )
            )

    assert waiting.job_id in {j.job_id for j in store.waiting_jobs(user_id)}
    mine = next(r for r in store.running_jobs(user_id) if r.job.job_id == running.job_id)
    assert [c.chain_id for c in mine.chains] == [live]  # failed chain excluded


# ----- Event log --------------------------------------------------------------


def test_event_log_cursor_and_consumer_ack(pg_client: PostgresClient):
    log = PostgresEventLog(pg_client)
    first = Event(type="job.submitted", user_id="usr_e", payload_json={"n": 1})
    second = Event(type="chain.failed", user_id="usr_e", payload_json={"n": 2})
    log.append(first)
    log.append(second)

    assert [e.event_id for e in log.read_after(first.event_id)] == [second.event_id]
    assert second.event_id in {e.event_id for e in log.read_after(None, types={"chain.failed"})}

    consumer = f"koi-{first.event_id}"  # unique per run
    assert log.get_cursor(consumer) is None
    log.ack(consumer, first.event_id)
    assert log.get_cursor(consumer) == first.event_id
    assert [e.event_id for e in log.read_for_consumer(consumer)] == [second.event_id]
    log.ack(consumer, second.event_id)
    assert log.read_for_consumer(consumer) == []
