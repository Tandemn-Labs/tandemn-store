"""Integration tests for RedisStreamClient.

Requires `make up` or CI Redis service on localhost:56379.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tandemn_system_data.clients import RedisStreamClient
from tandemn_system_data.models import Event

pytestmark = pytest.mark.integration


@pytest.fixture
def streams() -> RedisStreamClient:
    client = RedisStreamClient()
    client.client.flushdb()
    return client


def _event(**overrides) -> Event:
    base = {
        "event_id": "evt_test_0000000000000000000000",
        "user_id": "usr_1",
        "job_id": "job_1",
        "chain_id": None,
        "type": "job.submitted",
        "payload_json": {"job_id": "job_1", "user_id": "usr_1"},
        "created_at": datetime.now(UTC),
    }
    base.update(overrides)
    return Event(**base)


def test_emit_and_replay_from_global_stream(streams: RedisStreamClient):
    event = _event()
    message_id = streams.emit(event)
    assert "-" in message_id

    messages = streams.read_range("events.global")
    assert len(messages) == 1
    assert messages[0].message_id == message_id
    assert messages[0].event.event_id == event.event_id
    assert messages[0].event.payload_json == event.payload_json


def test_emit_with_user_fanout(streams: RedisStreamClient):
    event = _event(user_id="usr_fanout")
    global_id, user_id = streams.emit_with_user_fanout(event)
    assert global_id
    assert user_id

    global_messages = streams.read_range("events.global")
    user_messages = streams.read_range("events.user.usr_fanout")
    assert len(global_messages) == 1
    assert len(user_messages) == 1
    assert user_messages[0].event.event_id == event.event_id


def test_emit_with_no_user_skips_user_fanout(streams: RedisStreamClient):
    event = _event(user_id=None)
    global_id, user_id = streams.emit_with_user_fanout(event)
    assert global_id
    assert user_id is None
    assert streams.read_range("events.global")


def test_consumer_group_read_and_ack(streams: RedisStreamClient):
    event = _event(event_id="evt_group_000000000000000000000")
    streams.emit(event)
    streams.create_group("events.global", "koi")

    messages = streams.read_group("events.global", "koi", "consumer-1", count=10)
    assert len(messages) == 1
    assert messages[0].event.event_id == event.event_id

    pending = streams.pending_summary("events.global", "koi")
    assert pending["pending"] == 1

    assert streams.ack("events.global", "koi", messages[0].message_id) == 1
    pending = streams.pending_summary("events.global", "koi")
    assert pending["pending"] == 0


def test_create_group_is_idempotent(streams: RedisStreamClient):
    streams.create_group("events.global", "koi")
    streams.create_group("events.global", "koi")


def test_pending_range_and_claim_stale(streams: RedisStreamClient):
    event = _event(event_id="evt_claim_000000000000000000000")
    streams.emit(event)
    streams.create_group("events.global", "koi")
    messages = streams.read_group("events.global", "koi", "consumer-1", count=1)
    assert len(messages) == 1

    pending = streams.pending_range("events.global", "koi", count=10)
    assert len(pending) == 1
    assert pending[0]["message_id"] == messages[0].message_id

    claimed = streams.claim_stale(
        "events.global",
        "koi",
        "consumer-2",
        [messages[0].message_id],
        min_idle_ms=0,
    )
    assert len(claimed) == 1
    assert claimed[0].event.event_id == event.event_id
    assert streams.ack("events.global", "koi", claimed[0].message_id) == 1


def test_user_stream_requires_user_id():
    with pytest.raises(ValueError):
        RedisStreamClient.user_stream("")
