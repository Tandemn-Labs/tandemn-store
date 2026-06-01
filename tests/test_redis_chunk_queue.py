"""Integration tests for Redis-backed chunk queue.

Requires Redis on localhost:56379 (`make up` or CI service container).
"""

from __future__ import annotations

import time

import pytest

from tandemn_system_data.clients import RedisChunkQueueAdmin
from tandemn_system_data.ids import new_job_id
from tandemn_user_data.core import OutputRef, PayloadRef, QueuedChunk
from tandemn_user_data.worker import RedisChunkQueueWorker

pytestmark = pytest.mark.integration


@pytest.fixture
def admin() -> RedisChunkQueueAdmin:
    q = RedisChunkQueueAdmin()
    q._r.flushdb()
    return q


@pytest.fixture
def worker() -> RedisChunkQueueWorker:
    return RedisChunkQueueWorker(lease_ttl_sec=1)


def _chunk(i: int) -> QueuedChunk:
    return QueuedChunk(
        chunk_id=f"chunk_{i}",
        payload_ref=PayloadRef(type="local", uri=f"/tmp/input-{i}.jsonl"),
        output_ref=OutputRef(type="local", uri=f"/tmp/output-{i}.jsonl"),
        num_records=10,
    )


def test_create_pull_complete_progress(admin: RedisChunkQueueAdmin, worker: RedisChunkQueueWorker):
    job_id = new_job_id()
    admin.create_job_queue(job_id, [_chunk(1), _chunk(2)])

    progress = admin.get_progress(job_id)
    assert progress.total == 2
    assert progress.pending == 2

    lease = worker.pull_chunk(job_id, "chain_1")
    assert lease is not None
    assert lease.chain_id == "chain_1"
    assert lease.payload_ref.uri.endswith("input-1.jsonl")

    progress = admin.get_progress(job_id)
    assert progress.pending == 1
    assert progress.inflight == 1

    assert worker.renew_lease(job_id, lease.chunk_id, "chain_1") is True
    assert worker.renew_lease(job_id, lease.chunk_id, "other_chain") is False

    progress = worker.complete_chunk(job_id, lease.chunk_id, "chain_1")
    assert progress.completed == 1
    assert progress.inflight == 0

    # idempotent completion
    progress = worker.complete_chunk(job_id, lease.chunk_id, "chain_1")
    assert progress.completed == 1


def test_no_double_pull(admin: RedisChunkQueueAdmin, worker: RedisChunkQueueWorker):
    job_id = new_job_id()
    admin.create_job_queue(job_id, [_chunk(1)])
    assert worker.pull_chunk(job_id, "chain_1") is not None
    assert worker.pull_chunk(job_id, "chain_2") is None


def test_reclaim_expired_requeues_until_max_retries(
    admin: RedisChunkQueueAdmin, worker: RedisChunkQueueWorker
):
    job_id = new_job_id()
    admin.create_job_queue(job_id, [_chunk(1)], max_retries=2)

    first = worker.pull_chunk(job_id, "chain_1")
    assert first is not None
    time.sleep(1.1)
    result = admin.reclaim_expired(job_id)
    assert result == {"reclaimed": 1, "failed": 0}
    assert admin.get_progress(job_id).pending == 1

    second = worker.pull_chunk(job_id, "chain_2")
    assert second is not None
    assert second.retry_count == 1
    time.sleep(1.1)
    result = admin.reclaim_expired(job_id)
    assert result == {"reclaimed": 0, "failed": 1}
    progress = admin.get_progress(job_id)
    assert progress.failed == 1
    assert progress.all_done is True


def test_force_reclaim(admin: RedisChunkQueueAdmin, worker: RedisChunkQueueWorker):
    job_id = new_job_id()
    admin.create_job_queue(job_id, [_chunk(1), _chunk(2)])
    a = worker.pull_chunk(job_id, "chain_a")
    b = worker.pull_chunk(job_id, "chain_b")
    assert a is not None and b is not None

    reclaimed = admin.force_reclaim(job_id, ["chain_a"])
    assert reclaimed == 1
    progress = admin.get_progress(job_id)
    assert progress.pending == 1
    assert progress.inflight == 1


def test_fail_chunk(admin: RedisChunkQueueAdmin, worker: RedisChunkQueueWorker):
    job_id = new_job_id()
    admin.create_job_queue(job_id, [_chunk(1)])
    lease = worker.pull_chunk(job_id, "chain_1")
    assert lease is not None

    progress = worker.fail_chunk(job_id, lease.chunk_id, "chain_1", "WORKER_ERROR")
    assert progress.failed == 1
    assert progress.all_done is True


def test_output_order_and_cleanup(admin: RedisChunkQueueAdmin):
    job_id = new_job_id()
    admin.create_job_queue(job_id, [_chunk(1), _chunk(2)])
    assert admin.get_output_order(job_id) == ["chunk_1", "chunk_2"]
    admin.cleanup_job(job_id)
    assert admin.get_progress(job_id).total == 0
    assert admin.get_output_order(job_id) == []
