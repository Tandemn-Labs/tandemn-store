"""Unit tests for worker-side OrcaChunkClient."""

from __future__ import annotations

import httpx
import pytest

from tandemn_user_data.core import ChunkLease, ChunkProgress, OutputRef, PayloadRef
from tandemn_user_data.worker import OrcaChunkClient


def _lease_json() -> dict:
    return ChunkLease(
        chunk_id="chunk_1",
        job_id="job_1",
        chain_id="chain_1",
        payload_ref=PayloadRef(type="local", uri="/tmp/in.jsonl"),
        output_ref=OutputRef(type="local", uri="/tmp/out.jsonl"),
        lease_until=123.0,
        retry_count=0,
        num_records=10,
    ).model_dump(mode="json")


def _progress_json() -> dict:
    return ChunkProgress(
        total=1,
        pending=0,
        inflight=0,
        completed=1,
        failed=0,
        all_done=True,
    ).model_dump(mode="json")


def test_constructor_requires_base_url():
    with pytest.raises(ValueError):
        OrcaChunkClient("")


def test_pull_chunk_returns_lease(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update({"url": url, "params": params, "headers": headers})
        return httpx.Response(200, json=_lease_json())

    monkeypatch.setattr(httpx, "get", fake_get)
    client = OrcaChunkClient("http://orca", token="tok")
    lease = client.pull_chunk("job_1", "chain_1")
    assert lease is not None
    assert lease.chunk_id == "chunk_1"
    assert captured["url"] == "http://orca/chunks/next"
    assert captured["params"] == {"job_id": "job_1", "chain_id": "chain_1"}
    assert captured["headers"] == {"X-Tandemn-Worker-Token": "tok"}


def test_pull_chunk_returns_none_on_204(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(204))
    assert OrcaChunkClient("http://orca").pull_chunk("job_1", "chain_1") is None


def test_renew_lease_false_on_409(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(409))
    assert OrcaChunkClient("http://orca").renew_lease("job_1", "chunk_1", "chain_1") is False


def test_renew_lease_success(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json={"renewed": True}))
    assert OrcaChunkClient("http://orca").renew_lease("job_1", "chunk_1", "chain_1") is True


def test_complete_chunk_returns_progress(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json=_progress_json()))
    progress = OrcaChunkClient("http://orca").complete_chunk("job_1", "chunk_1", "chain_1")
    assert progress.completed == 1
    assert progress.all_done is True


def test_fail_chunk_returns_progress(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json=_progress_json()))
    progress = OrcaChunkClient("http://orca").fail_chunk(
        "job_1", "chunk_1", "chain_1", "WORKER_ERROR"
    )
    assert progress.failed == 0


def test_error_translation(monkeypatch):
    client = OrcaChunkClient("http://orca")

    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(401))
    with pytest.raises(PermissionError):
        client.pull_chunk("job_1", "chain_1")

    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(404))
    with pytest.raises(KeyError):
        client.pull_chunk("job_1", "chain_1")

    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(500, text="boom"))
    with pytest.raises(RuntimeError):
        client.pull_chunk("job_1", "chain_1")
