"""Unit tests for tandemn_user_data: refs, connectors, worker path,
credential resolver. Uses the test-only local connector; the S3 path is
covered in test_s3_integration.py. The import boundary is enforced by
import-linter, not tests."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from tandemn_user_data.connectors.jsonl import record_from_jsonl_row
from tandemn_user_data.core import (
    ConnectorRegistry,
    HttpCredentialResolver,
    NormalizedRecord,
    OutputRef,
    PayloadRef,
)
from tandemn_user_data.orca import index_source
from tandemn_user_data.worker import WorkerClient, default_registry
from tests.local_connector import LocalFileConnector


@pytest.fixture
def input_jsonl(tmp_path: Path) -> Path:
    path = tmp_path / "inputs.jsonl"
    with path.open("w") as f:
        for i in range(6):
            f.write(
                json.dumps(
                    {
                        "input_id": f"in_{i}",
                        "user_id": "usr_1",
                        "job_id": "job_1",
                        "prompt": f"prompt {i}",
                    }
                )
                + "\n"
            )
    return path


@pytest.fixture
def registry() -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.register(LocalFileConnector())
    return reg


# ----- Core types ------------------------------------------------------------


def test_refs_forbid_extras_and_default_to_jsonl():
    ref = PayloadRef(type="s3", uri="s3://b/k", credentials_ref="cred_1")
    assert ref.format == "jsonl" and ref.byte_range is None
    with pytest.raises(ValidationError):
        PayloadRef(type="s3", uri="s3://b/k", bogus="nope")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        OutputRef(type="s3", uri="s3://b/", bogus="nope")  # type: ignore[call-arg]


def test_jsonl_parses_openai_batch_rows():
    rec = record_from_jsonl_row(
        {
            "custom_id": "req-1",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {"model": "Qwen/Qwen3-0.6B", "messages": [{"role": "user", "content": "hi"}]},
        }
    )
    assert rec.input_id == "req-1"
    assert rec.prompt == "hi"
    assert rec.metadata["openai_batch"]["body"]["model"] == "Qwen/Qwen3-0.6B"


# ----- Registry + Orca-side indexing -----------------------------------------


def test_registry_lookup_and_unknown_type(registry: ConnectorRegistry):
    assert registry.input_for("local") is registry.output_for("local")
    with pytest.raises(KeyError):
        registry.input_for("nope")
    assert default_registry().input_for("s3") is not None  # MVP default is S3-only


def test_index_source_chunks_by_byte_range(input_jsonl: Path, registry: ConnectorRegistry):
    refs = list(
        index_source(
            {"type": "local", "uri": str(input_jsonl), "chunk_size_lines": 2},
            registry=registry,
        )
    )
    assert len(refs) == 3  # 6 lines / 2
    with pytest.raises(ValueError):
        list(index_source({"uri": "/tmp/x"}, registry=registry))  # missing type


# ----- Worker path -----------------------------------------------------------


def test_worker_fetch_write_round_trip(
    input_jsonl: Path, tmp_path: Path, registry: ConnectorRegistry
):
    """Index -> fetch (as dicts, like chunk metadata arrives) -> write -> re-fetch."""
    client = WorkerClient(registry=registry)

    refs = list(
        index_source(
            {"type": "local", "uri": str(input_jsonl), "chunk_size_lines": 2},
            registry=registry,
        )
    )
    fetched: list[NormalizedRecord] = []
    for ref in refs:
        fetched.extend(client.fetch_payload(ref.model_dump()))
    assert [r.input_id for r in fetched] == [f"in_{i}" for i in range(6)]

    target = tmp_path / "outputs.jsonl"
    n = client.write_outputs(OutputRef(type="local", uri=str(target)), fetched)
    assert n == 6
    read_back = list(client.fetch_payload({"type": "local", "uri": str(target)}))
    assert [r.prompt for r in read_back] == [f"prompt {i}" for i in range(6)]


def test_worker_resolves_credentials_ref(input_jsonl: Path, registry: ConnectorRegistry):
    calls: list[str | None] = []

    class RecordingResolver:
        def resolve(self, credentials_ref):
            calls.append(credentials_ref)
            return None

    client = WorkerClient(registry=registry, resolver=RecordingResolver())
    ref = PayloadRef(type="local", uri=str(input_jsonl), credentials_ref="cred_abc")
    list(client.fetch_payload(ref))
    assert calls == ["cred_abc"]


# ----- HttpCredentialResolver -------------------------------------------------


def test_resolver_never_caches_and_translates_errors(monkeypatch):
    """Credentials are short-lived: every resolve must hit the server so
    expiry (410) is enforced server-side."""
    import tandemn_user_data.core.credentials_client as cc

    with pytest.raises(ValueError):
        HttpCredentialResolver(base_url="", token="t")
    with pytest.raises(ValueError):
        HttpCredentialResolver(base_url="http://x", token="")

    r = HttpCredentialResolver(base_url="http://x", token="t")
    assert r.resolve(None) is None

    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return httpx.Response(200, json={"secret_payload": {"x": calls["n"]}})

    monkeypatch.setattr(cc.httpx, "get", fake_get)
    assert r.resolve("cred_1") == {"x": 1}
    assert r.resolve("cred_1") == {"x": 2}  # no cache

    for status, exc in [(404, KeyError), (410, PermissionError), (401, PermissionError)]:
        monkeypatch.setattr(
            cc.httpx, "get", lambda url, headers=None, timeout=None, s=status: httpx.Response(s)
        )
        with pytest.raises(exc):
            r.resolve("cred_x")
