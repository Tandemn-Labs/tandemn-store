r"""Integration: S3Connector against MinIO.

Requires \`make up\`. Uses the docker-compose MinIO credentials.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator

import boto3
import pytest
from botocore.client import Config

from tandemn_user_data.connectors import S3Connector
from tandemn_user_data.core import NormalizedRecord, OutputRef, PayloadRef

pytestmark = pytest.mark.integration


MINIO_ENDPOINT = "http://localhost:59000"
MINIO_ACCESS_KEY = "tandemn"
MINIO_SECRET_KEY = "tandemn-dev-key"


def _creds() -> dict[str, str]:
    return {
        "endpoint": MINIO_ENDPOINT,
        "region": "us-east-1",
        "access_key": MINIO_ACCESS_KEY,
        "secret_key": MINIO_SECRET_KEY,
    }


def _raw_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
        config=Config(signature_version="s3v4"),
    )


@pytest.fixture
def bucket() -> Iterator[str]:
    """Create a fresh bucket per test and clean it up afterward."""
    name = f"tandemn-test-{uuid.uuid4().hex[:8]}"
    s3 = _raw_client()
    s3.create_bucket(Bucket=name)
    try:
        yield name
    finally:
        # Empty then delete.
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=name):
            for obj in page.get("Contents", []) or []:
                s3.delete_object(Bucket=name, Key=obj["Key"])
        s3.delete_bucket(Bucket=name)


def _put_jsonl(bucket: str, key: str, records: list[dict]) -> None:
    body = "\n".join(json.dumps(r) for r in records).encode("utf-8") + b"\n"
    _raw_client().put_object(Bucket=bucket, Key=key, Body=body)


def _openai_row(input_id: str, prompt: str) -> dict:
    return {
        "custom_id": input_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": "Qwen/Qwen3-0.6B",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": prompt},
            ],
        },
    }


# ---------------------------------------------------------------------------
# index()
# ---------------------------------------------------------------------------


def test_index_prefix_emits_one_payload_ref_per_object(bucket: str):
    # Seed three JSONL files under inputs/.
    for i in range(3):
        _put_jsonl(
            bucket,
            f"inputs/part-{i:03d}.jsonl",
            [_openai_row(f"in_{i}_{j}", f"prompt {i}.{j}") for j in range(2)],
        )

    conn = S3Connector()
    refs = list(
        conn.index(
            {"uri": f"s3://{bucket}/inputs/", "format": "jsonl"},
            creds=_creds(),
        )
    )
    assert len(refs) == 3
    for ref in refs:
        assert ref.type == "s3"
        assert ref.uri.startswith(f"s3://{bucket}/inputs/part-")
        assert ref.byte_range is None


def test_index_single_object_emits_one_ref(bucket: str):
    _put_jsonl(
        bucket,
        "inputs/single.jsonl",
        [_openai_row("i", "p")],
    )
    conn = S3Connector()
    refs = list(
        conn.index(
            {"uri": f"s3://{bucket}/inputs/single.jsonl", "format": "jsonl"},
            creds=_creds(),
        )
    )
    assert len(refs) == 1
    assert refs[0].uri == f"s3://{bucket}/inputs/single.jsonl"


# ---------------------------------------------------------------------------
# read()
# ---------------------------------------------------------------------------


def test_read_returns_normalized_records(bucket: str):
    _put_jsonl(
        bucket,
        "inputs/x.jsonl",
        [_openai_row(f"in_{i}", f"prompt {i}") for i in range(4)],
    )

    conn = S3Connector()
    refs = list(
        conn.index(
            {"uri": f"s3://{bucket}/inputs/", "format": "jsonl"},
            creds=_creds(),
        )
    )
    records = list(conn.read(refs[0], creds=_creds()))
    assert [r.input_id for r in records] == [f"in_{i}" for i in range(4)]
    assert records[0].metadata["openai_batch"]["body"]["model"] == "Qwen/Qwen3-0.6B"


def test_read_rejects_wrong_type():
    conn = S3Connector()
    with pytest.raises(ValueError):
        list(conn.read(PayloadRef(type="local", uri="/tmp/x")))


# ---------------------------------------------------------------------------
# write()
# ---------------------------------------------------------------------------


def test_write_to_prefix_creates_part_object(bucket: str):
    conn = S3Connector()
    ref = OutputRef(type="s3", uri=f"s3://{bucket}/outputs/")
    records = [
        NormalizedRecord(
            input_id=f"in_{i}",
            user_id="usr_1",
            job_id="job_1",
            prompt=f"reply {i}",
        )
        for i in range(3)
    ]
    n = conn.write(ref, records, creds=_creds())
    assert n == 3

    # List what we wrote.
    s3 = _raw_client()
    listing = s3.list_objects_v2(Bucket=bucket, Prefix="outputs/").get("Contents", [])
    assert len(listing) == 1
    key = listing[0]["Key"]
    assert key.startswith("outputs/part-")
    assert key.endswith(".jsonl")

    # Round-trip read via the connector.
    out_records = list(
        conn.read(
            PayloadRef(type="s3", uri=f"s3://{bucket}/{key}"),
            creds=_creds(),
        )
    )
    assert [r.prompt for r in out_records] == [f"reply {i}" for i in range(3)]


def test_write_zero_records_creates_no_object(bucket: str):
    conn = S3Connector()
    ref = OutputRef(type="s3", uri=f"s3://{bucket}/outputs/")
    n = conn.write(ref, [], creds=_creds())
    assert n == 0
    s3 = _raw_client()
    contents = s3.list_objects_v2(Bucket=bucket, Prefix="outputs/").get("Contents", [])
    assert contents == []


def test_round_trip_index_read_write_read(bucket: str):
    """Full lifecycle: write inputs, index them, read them, write outputs,
    index outputs, read outputs."""
    conn = S3Connector()
    # Seed
    in_records = [_openai_row(f"in_{i}", f"prompt {i}") for i in range(5)]
    _put_jsonl(bucket, "inputs/x.jsonl", in_records)

    # Index + read inputs
    refs = list(
        conn.index(
            {"uri": f"s3://{bucket}/inputs/", "format": "jsonl"},
            creds=_creds(),
        )
    )
    parsed = list(conn.read(refs[0], creds=_creds()))
    assert len(parsed) == 5

    # Generate fake outputs and write under outputs/.
    outputs = [
        NormalizedRecord(
            input_id=p.input_id,
            user_id=p.user_id,
            job_id=p.job_id,
            prompt=f"reply to: {p.prompt}",
        )
        for p in parsed
    ]
    conn.write(
        OutputRef(type="s3", uri=f"s3://{bucket}/outputs/"),
        outputs,
        creds=_creds(),
    )

    # Index + read outputs.
    out_refs = list(
        conn.index(
            {"uri": f"s3://{bucket}/outputs/", "format": "jsonl"},
            creds=_creds(),
        )
    )
    assert len(out_refs) == 1
    read_back = list(conn.read(out_refs[0], creds=_creds()))
    assert [r.prompt for r in read_back] == [f"reply to: prompt {i}" for i in range(5)]
