"""Phase 1a integration smoke: connect to Postgres + MinIO.

Requires `make up` (docker-compose stack) to be running.
Skip these unless the integration marker is selected.
"""

from __future__ import annotations

import pytest

from tandemn_system_data.clients import (
    PostgresClient,
    S3BlobClient,
)

pytestmark = pytest.mark.integration


def test_postgres_ping():
    client = PostgresClient()
    assert client.ping() is True


def test_minio_ping_and_bucket():
    client = S3BlobClient()
    assert client.ping() is True
    client.ensure_bucket()
    # Idempotency: a second call must not raise.
    client.ensure_bucket()
