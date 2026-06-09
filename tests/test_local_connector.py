"""Unit tests for LocalFileConnector — DATA_ARCHITECTURE.md §7."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tandemn_user_data.connectors import LocalFileConnector
from tandemn_user_data.core import NormalizedRecord, OutputRef, PayloadRef

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def input_jsonl(tmp_path: Path) -> Path:
    """A 25-line JSONL file with structured records."""
    path = tmp_path / "inputs.jsonl"
    with path.open("w") as f:
        for i in range(25):
            f.write(
                json.dumps(
                    {
                        "custom_id": f"in_{i}",
                        "method": "POST",
                        "url": "/v1/chat/completions",
                        "body": {
                            "model": "Qwen/Qwen3-0.6B",
                            "messages": [
                                {"role": "system", "content": "You are helpful."},
                                {"role": "user", "content": f"prompt {i}"},
                            ],
                        },
                    }
                )
            )
            f.write("\n")
    return path


# ---------------------------------------------------------------------------
# index()
# ---------------------------------------------------------------------------


def test_index_emits_payload_refs_in_byte_ranges(input_jsonl: Path):
    conn = LocalFileConnector()
    refs = list(conn.index({"uri": str(input_jsonl), "format": "jsonl", "chunk_size_lines": 10}))
    # 25 lines, chunk_size=10 -> 3 chunks (10 + 10 + 5).
    assert len(refs) == 3
    for ref in refs:
        assert ref.type == "local"
        assert ref.uri == str(input_jsonl)
        assert ref.byte_range is not None
        start, end = ref.byte_range
        assert end > start

    # Byte ranges should be contiguous and cover the whole file.
    full_size = input_jsonl.stat().st_size
    assert refs[0].byte_range[0] == 0
    for prev, curr in zip(refs, refs[1:], strict=False):
        assert prev.byte_range[1] == curr.byte_range[0]
    assert refs[-1].byte_range[1] == full_size


def test_index_single_chunk_when_chunk_size_exceeds_file(input_jsonl: Path):
    conn = LocalFileConnector()
    refs = list(conn.index({"uri": str(input_jsonl), "format": "jsonl", "chunk_size_lines": 1000}))
    assert len(refs) == 1


def test_index_rejects_missing_file(tmp_path: Path):
    conn = LocalFileConnector()
    with pytest.raises(FileNotFoundError):
        list(conn.index({"uri": str(tmp_path / "no.jsonl"), "format": "jsonl"}))


def test_index_rejects_non_jsonl_format(input_jsonl: Path):
    conn = LocalFileConnector()
    with pytest.raises(NotImplementedError):
        list(conn.index({"uri": str(input_jsonl), "format": "parquet"}))


def test_index_rejects_bad_chunk_size(input_jsonl: Path):
    conn = LocalFileConnector()
    with pytest.raises(ValueError):
        list(conn.index({"uri": str(input_jsonl), "format": "jsonl", "chunk_size_lines": 0}))


# ---------------------------------------------------------------------------
# read()
# ---------------------------------------------------------------------------


def test_read_returns_normalized_records(input_jsonl: Path):
    conn = LocalFileConnector()
    refs = list(conn.index({"uri": str(input_jsonl), "format": "jsonl", "chunk_size_lines": 10}))
    first_chunk = list(conn.read(refs[0]))
    assert len(first_chunk) == 10
    assert all(isinstance(r, NormalizedRecord) for r in first_chunk)
    assert first_chunk[0].input_id == "in_0"
    assert first_chunk[0].prompt == "prompt 0"
    assert first_chunk[0].metadata["openai_batch"]["body"]["model"] == "Qwen/Qwen3-0.6B"
    assert first_chunk[-1].input_id == "in_9"


def test_read_round_trip_full_file(input_jsonl: Path):
    conn = LocalFileConnector()
    refs = list(conn.index({"uri": str(input_jsonl), "format": "jsonl", "chunk_size_lines": 7}))
    all_records: list[NormalizedRecord] = []
    for ref in refs:
        all_records.extend(conn.read(ref))
    assert [r.input_id for r in all_records] == [f"in_{i}" for i in range(25)]


def test_read_without_byte_range_reads_whole_file(input_jsonl: Path):
    conn = LocalFileConnector()
    ref = PayloadRef(type="local", uri=str(input_jsonl))
    records = list(conn.read(ref))
    assert len(records) == 25


def test_read_rejects_wrong_type():
    conn = LocalFileConnector()
    with pytest.raises(ValueError):
        list(conn.read(PayloadRef(type="s3", uri="s3://x")))


# ---------------------------------------------------------------------------
# write()
# ---------------------------------------------------------------------------


def test_write_appends_normalized_records(tmp_path: Path):
    conn = LocalFileConnector()
    target = tmp_path / "outputs" / "part-000.jsonl"
    ref = OutputRef(type="local", uri=str(target))
    records = [
        NormalizedRecord(
            input_id=f"in_{i}",
            user_id="usr_1",
            job_id="job_1",
            prompt=f"reply {i}",
        )
        for i in range(5)
    ]
    n = conn.write(ref, iter(records))
    assert n == 5
    assert target.exists()

    # Round-trip back through read to confirm format.
    read_back = list(conn.read(PayloadRef(type="local", uri=str(target))))
    assert [r.input_id for r in read_back] == [f"in_{i}" for i in range(5)]
    assert [r.prompt for r in read_back] == [f"reply {i}" for i in range(5)]


def test_write_appends_across_calls(tmp_path: Path):
    conn = LocalFileConnector()
    target = tmp_path / "outputs.jsonl"
    ref = OutputRef(type="local", uri=str(target))

    rec = NormalizedRecord(input_id="in_x", user_id="t", job_id="j", prompt="p")
    conn.write(ref, [rec])
    conn.write(ref, [rec])
    read_back = list(conn.read(PayloadRef(type="local", uri=str(target))))
    assert len(read_back) == 2
