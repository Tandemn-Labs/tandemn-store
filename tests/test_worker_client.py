"""Worker-side fetch_payload / write_outputs tests.

Unit-style tests use LocalFileConnector + NullResolver. The S3 path is
covered end-to-end in test_s3_connector.py and reused implicitly when
WorkerClient delegates to the registered S3Connector.

Anchored to DATA_ARCHITECTURE.md §7 (worker fetches via PayloadRef,
resolves credentials_ref to short-lived tokens, never holds long-lived
customer credentials).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tandemn_user_data.core import (
    ConnectorRegistry,
    LocalCredentialsCache,
    NormalizedRecord,
    NullResolver,
    OutputRef,
    PayloadRef,
)
from tandemn_user_data.worker import (
    WorkerClient,
    default_registry,
    fetch_payload,
    write_outputs,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Default registry + WorkerClient construction
# ---------------------------------------------------------------------------


def test_default_registry_registers_local_and_s3():
    reg = default_registry()
    assert "local" in reg.known_input_types()
    assert "s3" in reg.known_input_types()
    assert "local" in reg.known_output_types()
    assert "s3" in reg.known_output_types()


def test_worker_client_uses_null_resolver_by_default():
    client = WorkerClient()
    assert isinstance(client._resolver, NullResolver)


# ---------------------------------------------------------------------------
# fetch_payload — LocalFileConnector path
# ---------------------------------------------------------------------------


def test_fetch_payload_with_payload_ref_object(input_jsonl: Path):
    client = WorkerClient()
    ref = PayloadRef(type="local", uri=str(input_jsonl))
    records = list(client.fetch_payload(ref))
    assert len(records) == 6
    assert all(isinstance(r, NormalizedRecord) for r in records)
    assert records[0].prompt == "prompt 0"


def test_fetch_payload_accepts_plain_dict(input_jsonl: Path):
    """Workers pop chunks as dicts from Redis; WorkerClient should
    coerce them to PayloadRef."""
    records = list(fetch_payload({"type": "local", "uri": str(input_jsonl), "format": "jsonl"}))
    assert len(records) == 6


def test_fetch_payload_unknown_type_raises():
    client = WorkerClient()
    with pytest.raises(KeyError):
        list(client.fetch_payload(PayloadRef(type="nonexistent", uri="x")))


# ---------------------------------------------------------------------------
# write_outputs
# ---------------------------------------------------------------------------


def test_write_outputs_round_trips_through_local(tmp_path: Path):
    target = tmp_path / "outputs.jsonl"
    n = write_outputs(
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
    # Read back through the same machinery.
    read_back = list(fetch_payload({"type": "local", "uri": str(target)}))
    assert [r.prompt for r in read_back] == [f"reply {i}" for i in range(3)]


# ---------------------------------------------------------------------------
# Credential resolution (§7)
# ---------------------------------------------------------------------------


def test_resolver_is_called_with_credentials_ref(input_jsonl: Path):
    """When a PayloadRef carries credentials_ref, the resolver must be
    invoked with exactly that ref."""

    calls: list[str | None] = []

    class RecordingResolver:
        def resolve(self, credentials_ref):
            calls.append(credentials_ref)
            return None

    client = WorkerClient(resolver=RecordingResolver())
    ref = PayloadRef(
        type="local",
        uri=str(input_jsonl),
        credentials_ref="cred_abc",
    )
    list(client.fetch_payload(ref))
    assert calls == ["cred_abc"]


def test_local_credentials_cache_used_for_s3_shaped_creds():
    """Confirms the cache resolves the value a worker would pass to a
    real connector. Connector itself is not invoked here."""
    cache = LocalCredentialsCache()
    cache.put(
        "cred_abc",
        {"access_key": "k", "secret_key": "s", "endpoint": "http://minio"},
    )
    client = WorkerClient(
        registry=ConnectorRegistry(),  # empty registry; we only test resolver path
        resolver=cache,
    )
    assert client._resolver.resolve("cred_abc") == {
        "access_key": "k",
        "secret_key": "s",
        "endpoint": "http://minio",
    }
