"""Worker-side WorkerClient tests (DATA_ARCHITECTURE.md §7).

Uses the test-only local connector + NullResolver; the S3 path is
covered in test_s3_connector.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tandemn_user_data.core import (
    ConnectorRegistry,
    NormalizedRecord,
    NullResolver,
    OutputRef,
    PayloadRef,
)
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
            )
            f.write("\n")
    return path


@pytest.fixture
def registry() -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.register(LocalFileConnector())
    return reg


def test_default_registry_registers_s3():
    reg = default_registry()
    assert reg.input_for("s3") is not None
    assert reg.output_for("s3") is not None


def test_worker_client_uses_null_resolver_by_default():
    client = WorkerClient()
    assert isinstance(client._resolver, NullResolver)


def test_fetch_payload_with_payload_ref_object(input_jsonl: Path, registry: ConnectorRegistry):
    client = WorkerClient(registry=registry)
    ref = PayloadRef(type="local", uri=str(input_jsonl))
    records = list(client.fetch_payload(ref))
    assert len(records) == 6
    assert all(isinstance(r, NormalizedRecord) for r in records)
    assert records[0].prompt == "prompt 0"


def test_fetch_payload_accepts_plain_dict(input_jsonl: Path, registry: ConnectorRegistry):
    """Workers receive chunk metadata as dicts; WorkerClient must coerce."""
    client = WorkerClient(registry=registry)
    records = list(client.fetch_payload({"type": "local", "uri": str(input_jsonl)}))
    assert len(records) == 6


def test_fetch_payload_unknown_type_raises():
    client = WorkerClient()
    with pytest.raises(KeyError):
        list(client.fetch_payload(PayloadRef(type="nonexistent", uri="x")))


def test_write_outputs_round_trips_through_local(tmp_path: Path, registry: ConnectorRegistry):
    client = WorkerClient(registry=registry)
    target = tmp_path / "outputs.jsonl"
    n = client.write_outputs(
        OutputRef(type="local", uri=str(target)),
        [
            NormalizedRecord(
                input_id=f"in_{i}",
                user_id="usr_1",
                job_id="job_1",
                prompt=f"reply {i}",
            )
            for i in range(3)
        ],
    )
    assert n == 3
    read_back = list(client.fetch_payload({"type": "local", "uri": str(target)}))
    assert [r.prompt for r in read_back] == [f"reply {i}" for i in range(3)]


def test_resolver_is_called_with_credentials_ref(input_jsonl: Path, registry: ConnectorRegistry):
    calls: list[str | None] = []

    class RecordingResolver:
        def resolve(self, credentials_ref):
            calls.append(credentials_ref)
            return None

    client = WorkerClient(registry=registry, resolver=RecordingResolver())
    ref = PayloadRef(type="local", uri=str(input_jsonl), credentials_ref="cred_abc")
    list(client.fetch_payload(ref))
    assert calls == ["cred_abc"]
