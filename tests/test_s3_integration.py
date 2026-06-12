"""Integration: S3Connector and S3BlobClient against MinIO (the
S3-compatible test double). Requires `make up`."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.client import Config

from tandemn_system_data.clients import S3BlobClient
from tandemn_user_data.connectors import S3Connector
from tandemn_user_data.core import NormalizedRecord, OutputRef, PayloadRef

pytestmark = pytest.mark.integration

MINIO = {
    "endpoint": "http://localhost:59000",
    "region": "us-east-1",
    "access_key": "tandemn",
    "secret_key": "tandemn-dev-key",
}


def _raw_client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=MINIO["endpoint"],
        aws_access_key_id=MINIO["access_key"],
        aws_secret_access_key=MINIO["secret_key"],
        region_name=MINIO["region"],
        config=Config(signature_version="s3v4"),
    )


@pytest.fixture
def bucket() -> Iterator[str]:
    name = f"tandemn-test-{uuid.uuid4().hex[:8]}"
    s3 = _raw_client()
    s3.create_bucket(Bucket=name)
    try:
        yield name
    finally:
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=name):
            for obj in page.get("Contents", []) or []:
                s3.delete_object(Bucket=name, Key=obj["Key"])
        s3.delete_bucket(Bucket=name)


def _openai_row(input_id: str, prompt: str) -> dict:
    return {
        "custom_id": input_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {"model": "Qwen/Qwen3-0.6B", "messages": [{"role": "user", "content": prompt}]},
    }


def test_blob_client_ping_and_bucket():
    """S3BlobClient is for Tandemn-owned blobs only."""
    client = S3BlobClient()
    assert client.ping() is True
    client.ensure_bucket()
    client.ensure_bucket()  # idempotent


def test_connector_full_round_trip(bucket: str):
    """Index inputs (one PayloadRef per object), read OpenAI batch rows,
    write outputs to a prefix, read them back."""
    conn = S3Connector()
    s3 = _raw_client()

    for i in range(2):
        body = "\n".join(
            json.dumps(_openai_row(f"in_{i}_{j}", f"prompt {i}.{j}")) for j in range(3)
        )
        s3.put_object(Bucket=bucket, Key=f"inputs/part-{i}.jsonl", Body=body.encode() + b"\n")

    refs = list(conn.index({"uri": f"s3://{bucket}/inputs/", "format": "jsonl"}, creds=MINIO))
    assert len(refs) == 2  # one ref per object
    assert all(r.type == "s3" for r in refs)

    records = [rec for ref in refs for rec in conn.read(ref, creds=MINIO)]
    assert len(records) == 6
    assert records[0].metadata["openai_batch"]["body"]["model"] == "Qwen/Qwen3-0.6B"

    outputs = [
        NormalizedRecord(
            input_id=r.input_id, user_id="usr_1", job_id="job_1", prompt=f"re: {r.prompt}"
        )
        for r in records
    ]
    # Writes to a prefix create a unique part object (S3 has no append).
    assert (
        conn.write(OutputRef(type="s3", uri=f"s3://{bucket}/outputs/"), outputs, creds=MINIO) == 6
    )
    assert conn.write(OutputRef(type="s3", uri=f"s3://{bucket}/outputs/"), [], creds=MINIO) == 0

    out_refs = list(conn.index({"uri": f"s3://{bucket}/outputs/", "format": "jsonl"}, creds=MINIO))
    assert len(out_refs) == 1  # zero-record write created no object
    read_back = [rec for ref in out_refs for rec in conn.read(ref, creds=MINIO)]
    assert sorted(r.input_id for r in read_back) == sorted(r.input_id for r in records)


def test_connector_rejects_wrong_ref_type():
    with pytest.raises(ValueError):
        list(S3Connector().read(PayloadRef(type="local", uri="/tmp/x")))
