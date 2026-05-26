"""S3Connector — read / write / index JSONL on S3 (or MinIO).

Per DATA_ARCHITECTURE.md §7, this connector handles **user** S3 buckets.
It is intentionally separate from tandemn_system_data.clients.S3BlobClient,
which is for Tandemn-owned blobs only. The user-data path must not
import anything from tandemn_system_data.

Source / target shape:

  PayloadRef.type == OutputRef.type == "s3"
  uri:   "s3://bucket/prefix/object_or_prefix"

  source_spec (passed to index):
    { uri:        "s3://bucket/prefix/",
      format:     "jsonl",
      endpoint:   "https://s3.amazonaws.com",   # optional; MinIO override
      region:     "us-east-1",                  # optional
    }

Credentials, when present, are passed in per call by the worker via the
CredentialResolver. Shape:
    { access_key, secret_key, endpoint?, region? }
If creds is None, the connector falls back to its constructor defaults
and then to boto3's environment / IAM chain.

Indexing strategy: one PayloadRef per S3 object found under the prefix.
Range-splitting JSONL inside a single object is a future enhancement;
for blob-shaped inputs (one logical chunk per object) this is the right
default.
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

from tandemn_user_data.core.record import NormalizedRecord, OutputRef, PayloadRef

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Split an s3:// URI into (bucket, key). The key may be empty
    or end with '/' to indicate a prefix."""
    parsed = urlparse(uri)
    if parsed.scheme != "s3":
        raise ValueError(f"expected s3:// URI, got {uri!r}")
    if not parsed.netloc:
        raise ValueError(f"s3 URI missing bucket: {uri!r}")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


def _is_prefix(uri: str) -> bool:
    """A URI ending in '/' (or with no key at all) is a prefix."""
    _, key = _parse_s3_uri(uri)
    return key == "" or key.endswith("/")


# ---------------------------------------------------------------------------
# S3Connector
# ---------------------------------------------------------------------------


class S3Connector:
    """Reference connector for JSONL on S3 / MinIO."""

    type = "s3"

    def __init__(
        self,
        *,
        default_endpoint: str | None = None,
        default_region: str | None = None,
        default_access_key: str | None = None,
        default_secret_key: str | None = None,
    ) -> None:
        # Defaults used when the resolver returns None (e.g. running
        # against a public bucket or relying on boto3's IAM chain).
        self._default_endpoint = default_endpoint
        self._default_region = default_region
        self._default_access_key = default_access_key
        self._default_secret_key = default_secret_key

    # ----- client construction --------------------------------------------

    def _client(self, creds: dict[str, Any] | None):
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

    # ----- input -----------------------------------------------------------

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
            # List every object under the prefix; one PayloadRef per object.
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=key):
                for obj in page.get("Contents", []) or []:
                    obj_key = obj["Key"]
                    if obj_key.endswith("/"):
                        # ignore zero-byte "directory" markers
                        continue
                    yield PayloadRef(
                        type=self.type,
                        uri=f"s3://{bucket}/{obj_key}",
                        format="jsonl",
                    )
        else:
            # Single object — one PayloadRef.
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

        obj = s3.get_object(**get_kwargs)
        body = obj["Body"].read()

        for raw in body.splitlines():
            if not raw.strip():
                continue
            row = json.loads(raw)
            yield NormalizedRecord(
                input_id=str(row.get("input_id") or row.get("id") or ""),
                user_id=str(row.get("user_id") or ""),
                job_id=str(row.get("job_id") or ""),
                prompt=row.get("prompt", ""),
                metadata=row.get("metadata", {}) or {},
            )

    # ----- output ---------------------------------------------------------

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

        # S3 has no append. Each write() call produces one new object
        # under the prefix (if uri is a prefix) or overwrites the named
        # object (if uri is an exact key). Most callers will pass a
        # prefix and let the connector pick a unique part name.
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

        buf.seek(0)
        s3.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=buf.getvalue(),
            ContentType="application/x-ndjson",
        )
        return count
