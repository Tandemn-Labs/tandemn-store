"""Worker-side entry points: fetch_payload, write_outputs, WorkerClient."""

from __future__ import annotations

from tandemn_user_data.worker.client import (
    WorkerClient,
    default_registry,
    fetch_payload,
    write_outputs,
)

__all__ = ["WorkerClient", "default_registry", "fetch_payload", "write_outputs"]
