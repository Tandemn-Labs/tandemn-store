"""Tests for the Orca-side helpers in tandemn_user_data.orca.

Anchored to DATA_ARCHITECTURE.md §7:
  Orca mints credentials_ref, indexes the source into PayloadRefs,
  enqueues chunks; the worker resolves credentials_ref and fetches
  bytes directly from the user's data system.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tandemn_user_data.connectors import LocalFileConnector
from tandemn_user_data.core import (
    ConnectorRegistry,
    LocalCredentialsCache,
    NormalizedRecord,
    PayloadRef,
)
from tandemn_user_data.orca import (
    DevCredentialIssuer,
    IssuedCredential,
    index_source,
    index_source_to_list,
)
from tandemn_user_data.worker import WorkerClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def input_jsonl(tmp_path: Path) -> Path:
    path = tmp_path / "inputs.jsonl"
    with path.open("w") as f:
        for i in range(8):
            f.write(
                json.dumps(
                    {
                        "input_id": f"in_{i}",
                        "tenant_id": "tnt_1",
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


# ---------------------------------------------------------------------------
# indexer
# ---------------------------------------------------------------------------


def test_index_source_yields_payload_refs(input_jsonl: Path, registry: ConnectorRegistry):
    refs = list(
        index_source(
            {
                "type": "local",
                "uri": str(input_jsonl),
                "format": "jsonl",
                "chunk_size_lines": 3,
            },
            registry=registry,
        )
    )
    # 8 lines / 3 -> 3 chunks (3 + 3 + 2).
    assert len(refs) == 3
    assert all(isinstance(r, PayloadRef) for r in refs)


def test_index_source_to_list_returns_list(input_jsonl: Path, registry: ConnectorRegistry):
    refs = index_source_to_list(
        {"type": "local", "uri": str(input_jsonl), "format": "jsonl"},
        registry=registry,
    )
    assert isinstance(refs, list)
    assert len(refs) >= 1


def test_index_source_requires_type(registry: ConnectorRegistry):
    with pytest.raises(ValueError):
        list(index_source({"uri": "/tmp/x"}, registry=registry))


def test_index_source_unknown_type(registry: ConnectorRegistry):
    with pytest.raises(KeyError):
        list(index_source({"type": "nonexistent", "uri": "x"}, registry=registry))


# ---------------------------------------------------------------------------
# DevCredentialIssuer
# ---------------------------------------------------------------------------


def test_issuer_returns_unique_refs():
    issuer = DevCredentialIssuer()
    a = issuer.issue("tnt_1", {"prefix": "s3://a/"}, secret_payload={"k": "v"})
    b = issuer.issue("tnt_1", {"prefix": "s3://b/"}, secret_payload={"k": "v"})
    assert isinstance(a, IssuedCredential)
    assert a.credentials_ref != b.credentials_ref
    assert a.credentials_ref.startswith("cred_")


def test_issued_credential_has_future_expiry():
    issuer = DevCredentialIssuer()
    issued = issuer.issue("tnt_1", {}, secret_payload=None, ttl_seconds=60)
    assert issued.expires_at > datetime.now(UTC)


def test_issuer_rejects_bad_inputs():
    issuer = DevCredentialIssuer()
    with pytest.raises(ValueError):
        issuer.issue("", {}, secret_payload=None)
    with pytest.raises(ValueError):
        issuer.issue("tnt_1", {}, secret_payload=None, ttl_seconds=0)


def test_issuer_lookup():
    issuer = DevCredentialIssuer()
    issued = issuer.issue("tnt_1", {}, secret_payload={"x": 1})
    assert issuer.get(issued.credentials_ref) is issued
    assert issuer.get("cred_nonexistent") is None
    assert len(issuer) == 1
    assert list(issuer)[0] is issued


def test_bind_to_cache_exposes_only_secret_payload():
    issuer = DevCredentialIssuer()
    issued = issuer.issue(
        "tnt_1",
        scope={"prefix": "s3://x"},
        secret_payload={"access_key": "k", "secret_key": "s"},
    )
    cache = LocalCredentialsCache()
    issuer.bind_to_cache(cache)
    assert cache.resolve(issued.credentials_ref) == {
        "access_key": "k",
        "secret_key": "s",
    }


# ---------------------------------------------------------------------------
# End-to-end: Orca mints + indexes; worker resolves + fetches  (§7 sequence)
# ---------------------------------------------------------------------------


def test_full_section_7_dataflow(input_jsonl: Path, registry: ConnectorRegistry):
    # --- Orca side ----------------------------------------------------
    issuer = DevCredentialIssuer()
    issued = issuer.issue(
        "tnt_1",
        scope={"prefix": str(input_jsonl.parent)},
        # LocalFileConnector doesn't need creds, but the dataflow
        # still carries a credentials_ref through every chunk so the
        # contract is exercised exactly as the doc describes.
        secret_payload=None,
    )

    input_source = {
        "type": "local",
        "uri": str(input_jsonl),
        "format": "jsonl",
        "chunk_size_lines": 3,
        "credentials_ref": issued.credentials_ref,
    }

    # Orca indexes the source — bytes never transit Orca itself.
    refs = list(index_source(input_source, registry=registry))
    assert len(refs) == 3

    # Orca attaches credentials_ref onto each PayloadRef before enqueue.
    enqueued = [ref.model_copy(update={"credentials_ref": issued.credentials_ref}) for ref in refs]

    # --- Worker side --------------------------------------------------
    cache = LocalCredentialsCache()
    issuer.bind_to_cache(cache)
    worker = WorkerClient(registry=registry, resolver=cache)

    fetched: list[NormalizedRecord] = []
    for chunk in enqueued:
        # Workers pop chunks as dicts from Redis; pass them through as dicts.
        fetched.extend(worker.fetch_payload(chunk.model_dump()))

    assert [r.input_id for r in fetched] == [f"in_{i}" for i in range(8)]
