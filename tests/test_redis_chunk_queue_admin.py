"""Integration tests for Orca-side Redis chunk queue admin/client.

Requires Redis on localhost:56379 (`make up` or CI service container).
"""

from __future__ import annotations

import time

import pytest

from tandemn_system_data.clients import RedisChunkQueueAdmin
from tandemn_system_data.ids import new_job_id
from tandemn_user_data.core import OutputRef, PayloadRef, QueuedChunk

pytestmark = pytest.mark.integration


@pytest.fixture
def queue() -> RedisChunkQueueAdmin:
    q = RedisChunkQueueAdmin(lease_ttl_sec=1)
    q._r.flushdb()
    return q


def _chunk(i: int) -> QueuedChunk:
    return QueuedChunk(
        chunk_id=f"chunk_{i}",
        payload_ref=PayloadRef(type="local", uri=f"/tmp/input-{i}.jsonl"),
        output_ref=OutputRef(type="local", uri=f"/tmp/output-{i}.jsonl"),
        num_records=10,
    )


def test_create_pull_complete_progress(queue: RedisChunkQueueAdmin):
    job_id = new_job_id()
    queue.create_job_queue(job_id, [_chunk(1), _chunk(2)])

    assert queue.get_progress(job_id).pending == 2
    lease = queue.pull_chunk(job_id, "chain_1")
    assert lease is not None
    assert lease.chain_id == "chain_1"
    assert lease.payload_ref.uri.endswith("input-1.jsonl")

    assert queue.get_progress(job_id).inflight == 1
    assert queue.renew_lease(job_id, lease.chunk_id, "chain_1") is True
    assert queue.renew_lease(job_id, lease.chunk_id, "other_chain") is False

    progress = queue.complete_chunk(job_id, lease.chunk_id, "chain_1")
    assert progress.completed == 1
    assert progress.inflight == 0

    # idempotent completion
    assert queue.complete_chunk(job_id, lease.chunk_id, "chain_1").completed == 1


def test_no_double_pull(queue: RedisChunkQueueAdmin):
    job_id = new_job_id()
    queue.create_job_queue(job_id, [_chunk(1)])
    assert queue.pull_chunk(job_id, "chain_1") is not None
    assert queue.pull_chunk(job_id, "chain_2") is None


def test_reclaim_expired_requeues_until_max_retries(queue: RedisChunkQueueAdmin):
    job_id = new_job_id()
    queue.create_job_queue(job_id, [_chunk(1)], max_retries=2)

    first = queue.pull_chunk(job_id, "chain_1")
    assert first is not None
    time.sleep(1.1)
    assert queue.reclaim_expired(job_id) == {"reclaimed": 1, "failed": 0}

    second = queue.pull_chunk(job_id, "chain_2")
    assert second is not None
    assert second.retry_count == 1
    time.sleep(1.1)
    assert queue.reclaim_expired(job_id) == {"reclaimed": 0, "failed": 1}
    progress = queue.get_progress(job_id)
    assert progress.failed == 1
    assert progress.all_done is True


def test_force_reclaim(queue: RedisChunkQueueAdmin):
    job_id = new_job_id()
    queue.create_job_queue(job_id, [_chunk(1), _chunk(2)])
    assert queue.pull_chunk(job_id, "chain_a") is not None
    assert queue.pull_chunk(job_id, "chain_b") is not None

    assert queue.force_reclaim(job_id, ["chain_a"]) == 1
    progress = queue.get_progress(job_id)
    assert progress.pending == 1
    assert progress.inflight == 1


def test_fail_chunk(queue: RedisChunkQueueAdmin):
    job_id = new_job_id()
    queue.create_job_queue(job_id, [_chunk(1)])
    lease = queue.pull_chunk(job_id, "chain_1")
    assert lease is not None

    progress = queue.fail_chunk(job_id, lease.chunk_id, "chain_1", "WORKER_ERROR")
    assert progress.failed == 1
    assert progress.all_done is True


def test_output_order_and_cleanup(queue: RedisChunkQueueAdmin):
    job_id = new_job_id()
    queue.create_job_queue(job_id, [_chunk(1), _chunk(2)])
    assert queue.get_output_order(job_id) == ["chunk_1", "chunk_2"]
    queue.cleanup_job(job_id)
    assert queue.get_progress(job_id).total == 0
    assert queue.get_output_order(job_id) == []
