"""Tests for the Orca-side helpers in tandemn_user_data.orca.

Anchored to DATA_ARCHITECTURE.md §7: Orca indexes the source into
PayloadRefs, enqueues chunks, and the worker fetches bytes directly
from the user's data system.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tandemn_user_data.connectors import LocalFileConnector
from tandemn_user_data.core import (
    ConnectorRegistry,
    NormalizedRecord,
    PayloadRef,
)
from tandemn_user_data.orca import (
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
# End-to-end: Orca indexes; worker fetches (§7 sequence, no credentials needed)
# ---------------------------------------------------------------------------


def test_full_section_7_dataflow(input_jsonl: Path, registry: ConnectorRegistry):
    input_source = {
        "type": "local",
        "uri": str(input_jsonl),
        "format": "jsonl",
        "chunk_size_lines": 3,
    }

    # Orca indexes the source — bytes never transit Orca itself.
    refs = list(index_source(input_source, registry=registry))
    assert len(refs) == 3

    # --- Worker side --------------------------------------------------
    worker = WorkerClient(registry=registry)

    fetched: list[NormalizedRecord] = []
    for chunk in refs:
        # Workers pop chunks as dicts from the chunk queue; pass them through as dicts.
        fetched.extend(worker.fetch_payload(chunk.model_dump()))

    assert [r.input_id for r in fetched] == [f"in_{i}" for i in range(8)]
