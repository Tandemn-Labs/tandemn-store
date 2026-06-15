"""S3Connector — JSONL on user S3 buckets / MinIO (type "s3").

Handles user buckets only. This package runs on customer GPU nodes and
must not import tandemn_system_data.

source_spec for index():
    { uri: "s3://bucket/prefix/", format: "jsonl", endpoint?: ..., region?: ... }

Credentials arrive per call from the CredentialResolver as
{ access_key, secret_key, endpoint?, region? }. With creds=None the
connector falls back to constructor defaults, then boto3's env/IAM chain.

Indexing emits one PayloadRef per object under the prefix. Range-splitting
within an object is a future enhancement.
"""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.client import Config

from tandemn_user_data.connectors.jsonl import record_from_jsonl_row
from tandemn_user_data.core.record import NormalizedRecord, OutputRef, PayloadRef


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3":
        raise ValueError(f"expected s3:// URI, got {uri!r}")
    if not parsed.netloc:
        raise ValueError(f"s3 URI missing bucket: {uri!r}")
    return parsed.netloc, parsed.path.lstrip("/")


def _is_prefix(uri: str) -> bool:
    """A URI ending in '/' (or with no key at all) is a prefix."""
    _, key = _parse_s3_uri(uri)
    return key == "" or key.endswith("/")


class S3Connector:
    type = "s3"

    def __init__(
        self,
        *,
        default_endpoint: str | None = None,
        default_region: str | None = None,
        default_access_key: str | None = None,
        default_secret_key: str | None = None,
    ) -> None:
        self._default_endpoint = default_endpoint
        self._default_region = default_region
        self._default_access_key = default_access_key
        self._default_secret_key = default_secret_key

    def _client(self, creds: dict[str, Any] | None) -> Any:
        creds = creds or {}
        endpoint = creds.get("endpoint") or self._default_endpoint
        region = creds.get("region") or self._default_region or "us-east-1"
        access_key = creds.get("access_key") or self._default_access_key
        secret_key = creds.get("secret_key") or self._default_secret_key

        kwargs: dict[str, Any] = {
            "region_name": region,
            "config": Config(signature_version="s3v4"),
        }
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key

        return boto3.client("s3", **kwargs)

    def index(
        self,
        source_spec: dict[str, Any],
        creds: Any | None = None,
    ) -> Iterator[PayloadRef]:
        uri = source_spec["uri"]
        fmt = source_spec.get("format", "jsonl")
        if fmt != "jsonl":
            raise NotImplementedError(f"S3Connector only supports format='jsonl', got {fmt!r}")

        bucket, key = _parse_s3_uri(uri)
        s3 = self._client(creds)

        if _is_prefix(uri):
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=key):
                for obj in page.get("Contents", []) or []:
                    obj_key = obj["Key"]
                    if obj_key.endswith("/"):
                        # zero-byte "directory" markers
                        continue
                    yield PayloadRef(
                        type=self.type,
                        uri=f"s3://{bucket}/{obj_key}",
                        format="jsonl",
                    )
        else:
            yield PayloadRef(type=self.type, uri=uri, format="jsonl")

    def read(
        self,
        payload_ref: PayloadRef,
        creds: Any | None = None,
    ) -> Iterator[NormalizedRecord]:
        if payload_ref.type != self.type:
            raise ValueError(f"S3Connector cannot read payload_ref of type {payload_ref.type!r}")
        if payload_ref.format != "jsonl":
            raise NotImplementedError(
                f"S3Connector only supports format='jsonl', got {payload_ref.format!r}"
            )

        bucket, key = _parse_s3_uri(payload_ref.uri)
        s3 = self._client(creds)

        get_kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key}
        if payload_ref.byte_range is not None:
            start, end = payload_ref.byte_range
            # S3 Range is inclusive end; our byte_range is exclusive end.
            get_kwargs["Range"] = f"bytes={start}-{end - 1}"

        body = s3.get_object(**get_kwargs)["Body"].read()

        for raw in body.splitlines():
            if not raw.strip():
                continue
            yield record_from_jsonl_row(json.loads(raw))

    def write(
        self,
        output_ref: OutputRef,
        records: Iterable[NormalizedRecord],
        creds: Any | None = None,
    ) -> int:
        if output_ref.type != self.type:
            raise ValueError(f"S3Connector cannot write output_ref of type {output_ref.type!r}")
        if output_ref.format != "jsonl":
            raise NotImplementedError(
                f"S3Connector only supports format='jsonl', got {output_ref.format!r}"
            )

        bucket, key = _parse_s3_uri(output_ref.uri)
        s3 = self._client(creds)

        # S3 has no append: a prefix URI gets a unique part object per
        # write() call; an exact key is overwritten.
        if _is_prefix(output_ref.uri):
            object_key = f"{key}part-{uuid.uuid4().hex[:12]}.jsonl"
        else:
            object_key = key

        buf = io.BytesIO()
        count = 0
        for rec in records:
            buf.write(rec.model_dump_json().encode("utf-8"))
            buf.write(b"\n")
            count += 1

        if count == 0:
            return 0

        s3.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=buf.getvalue(),
            ContentType="application/x-ndjson",
        )
        return count
