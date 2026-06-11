"""Test-only local JSONL connector.

The product connector surface is S3-only; tests need a credential-less
connector that exercises the same protocols (index/read/write, byte_range
chunking) without object-store infrastructure.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from tandemn_user_data.connectors.jsonl import record_from_jsonl_row
from tandemn_user_data.core import NormalizedRecord, OutputRef, PayloadRef

DEFAULT_CHUNK_SIZE_LINES = 1000


class LocalFileConnector:
    type = "local"

    def index(
        self,
        source_spec: dict[str, Any],
        creds: Any | None = None,
    ) -> Iterator[PayloadRef]:
        path = Path(source_spec["uri"])
        chunk_size = int(source_spec.get("chunk_size_lines", DEFAULT_CHUNK_SIZE_LINES))
        if chunk_size <= 0:
            raise ValueError("chunk_size_lines must be > 0")
        if not path.is_file():
            raise FileNotFoundError(f"input source not found: {path}")

        with path.open("rb") as f:
            start = 0
            line_count = 0
            while True:
                line = f.readline()
                if not line:
                    end = f.tell()
                    if end > start:
                        yield PayloadRef(type=self.type, uri=str(path), byte_range=(start, end))
                    return
                line_count += 1
                if line_count >= chunk_size:
                    end = f.tell()
                    yield PayloadRef(type=self.type, uri=str(path), byte_range=(start, end))
                    start = end
                    line_count = 0

    def read(
        self,
        payload_ref: PayloadRef,
        creds: Any | None = None,
    ) -> Iterator[NormalizedRecord]:
        path = Path(payload_ref.uri)
        start, end = payload_ref.byte_range or (0, os.path.getsize(path))
        with path.open("rb") as f:
            f.seek(start)
            buf = f.read(end - start)
        for raw in buf.splitlines():
            if not raw.strip():
                continue
            yield record_from_jsonl_row(json.loads(raw))

    def write(
        self,
        output_ref: OutputRef,
        records: Iterable[NormalizedRecord],
        creds: Any | None = None,
    ) -> int:
        path = Path(output_ref.uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with path.open("ab") as f:
            for rec in records:
                f.write(rec.model_dump_json().encode("utf-8"))
                f.write(b"\n")
                count += 1
        return count
