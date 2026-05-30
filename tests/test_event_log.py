"""Integration tests for PostgresEventLog.

Requires `make up` or CI Postgres service on localhost:55432.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tandemn_system_data.clients import PostgresClient, PostgresEventLog
from tandemn_system_data.db import Base
from tandemn_system_data.models import Event

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def pg_client() -> PostgresClient:
    return PostgresClient()


@pytest.fixture(autouse=True)
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
def event_log(pg_client: PostgresClient) -> PostgresEventLog:
    return PostgresEventLog(pg_client)


def _event(event_id: str, *, type_: str = "job.submitted") -> Event:
    return Event(
        event_id=event_id,
        user_id="usr_1",
        job_id="job_1",
        chain_id=None,
        type=type_,
        payload_json={"event_id": event_id},
        created_at=datetime.now(UTC),
    )


def test_append_and_read_from_beginning(event_log: PostgresEventLog):
    event = _event("evt_log_0000000000000000000001")
    assert event_log.append(event) == event.event_id

    events = event_log.read_after(None)
    assert len(events) == 1
    assert events[0].event_id == event.event_id
    assert events[0].payload_json == {"event_id": event.event_id}


def test_read_after_cursor(event_log: PostgresEventLog):
    first = _event("evt_log_0000000000000000000002")
    second = _event("evt_log_0000000000000000000003")
    event_log.append(first)
    event_log.append(second)

    events = event_log.read_after(first.event_id)
    assert [e.event_id for e in events] == [second.event_id]


def test_read_filters_by_type(event_log: PostgresEventLog):
    a = _event("evt_log_0000000000000000000004", type_="job.submitted")
    b = _event("evt_log_0000000000000000000005", type_="chain.failed")
    event_log.append(a)
    event_log.append(b)

    events = event_log.read_after(None, types={"chain.failed"})
    assert [e.event_id for e in events] == [b.event_id]


def test_consumer_cursor_ack_flow(event_log: PostgresEventLog):
    a = _event("evt_log_0000000000000000000006")
    b = _event("evt_log_0000000000000000000007")
    event_log.append(a)
    event_log.append(b)

    assert event_log.get_cursor("koi") is None
    events = event_log.read_for_consumer("koi")
    assert [e.event_id for e in events] == [a.event_id, b.event_id]

    event_log.ack("koi", a.event_id)
    assert event_log.get_cursor("koi") == a.event_id
    events = event_log.read_for_consumer("koi")
    assert [e.event_id for e in events] == [b.event_id]

    event_log.ack("koi", b.event_id)
    assert event_log.read_for_consumer("koi") == []
