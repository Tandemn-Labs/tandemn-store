"""S3 / MinIO client for Tandemn-owned blobs only.

This is NOT used for user data. User payloads flow through
tandemn_user_data.connectors. This client handles internal artifacts:
staging for pre-shard, internal logs, dumps.
"""

from __future__ import annotations

import os
from typing import Any

import boto3
from botocore.client import Config

DEFAULT_ENDPOINT = "http://localhost:59000"
DEFAULT_ACCESS_KEY = "tandemn"
DEFAULT_SECRET_KEY = "tandemn-dev-key"
DEFAULT_REGION = "us-east-1"
DEFAULT_BUCKET = "tandemn-internal"


class S3BlobClient:
    """boto3 S3 client configured for MinIO in dev, real S3 in prod."""

    def __init__(
        self,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str | None = None,
        bucket: str | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url or os.getenv("TANDEMN_S3_ENDPOINT", DEFAULT_ENDPOINT)
        self.access_key = access_key or os.getenv("TANDEMN_S3_ACCESS_KEY", DEFAULT_ACCESS_KEY)
        self.secret_key = secret_key or os.getenv("TANDEMN_S3_SECRET_KEY", DEFAULT_SECRET_KEY)
        self.region = region or os.getenv("TANDEMN_S3_REGION", DEFAULT_REGION)
        self.bucket = bucket or os.getenv("TANDEMN_S3_BUCKET", DEFAULT_BUCKET)

        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            config=Config(signature_version="s3v4"),
        )

    @property
    def client(self) -> Any:
        return self._client

    def ensure_bucket(self) -> None:
        """Create the configured bucket if it doesn't exist."""
        existing = {b["Name"] for b in self._client.list_buckets().get("Buckets", [])}
        if self.bucket not in existing:
            self._client.create_bucket(Bucket=self.bucket)

    def ping(self) -> bool:
        """Return True if S3 / MinIO is reachable."""
        self._client.list_buckets()
        return True
