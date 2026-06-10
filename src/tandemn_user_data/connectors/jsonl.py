"""JSONL parsing shared by file/object connectors.

MVP input format is OpenAI Batch-style JSONL:

    {"custom_id": "req-1", "method": "POST", "url": "/v1/chat/completions", "body": {...}}

Rows without a `body` are parsed as the NormalizedRecord JSON shape our
output connectors emit, so outputs round-trip through the same readers.
"""

from __future__ import annotations

import json
from typing import Any

from tandemn_user_data.core import NormalizedRecord


def record_from_jsonl_row(row: dict[str, Any]) -> NormalizedRecord:
    if "body" in row and isinstance(row["body"], dict):
        return _openai_batch_row(row)
    return _normalized_row(row)


def _openai_batch_row(row: dict[str, Any]) -> NormalizedRecord:
    body = row["body"]
    messages = body.get("messages") or []
    prompt = _last_user_message(messages) or json.dumps(body, separators=(",", ":"))
    return NormalizedRecord(
        input_id=str(row.get("custom_id") or row.get("id") or row.get("input_id") or ""),
        user_id=str(row.get("user_id") or ""),
        job_id=str(row.get("job_id") or ""),
        prompt=prompt,
        metadata={
            "openai_batch": {
                "method": row.get("method"),
                "url": row.get("url"),
                "body": body,
            }
        },
    )


def _normalized_row(row: dict[str, Any]) -> NormalizedRecord:
    return NormalizedRecord(
        input_id=str(row.get("input_id") or row.get("id") or ""),
        user_id=str(row.get("user_id") or ""),
        job_id=str(row.get("job_id") or ""),
        prompt=row.get("prompt", ""),
        metadata=row.get("metadata", {}) or {},
    )


def _last_user_message(messages: Any) -> str | None:
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            return message["content"]
    return None
