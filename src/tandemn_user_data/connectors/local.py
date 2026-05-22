"""LocalFileConnector — read / write / index JSONL on local disk.

Per DATA_ARCHITECTURE.md §7, every connector implements both
InputConnector.index/read and OutputConnector.write. This one is the
reference implementation used for tests, demos, and on-prem deployments
where the customer data already sits on a shared filesystem.

Source / target shape:

  PayloadRef.type == OutputRef.type == "local"

  source_spec (passed to index):
    { uri: "/abs/path/to/inputs.jsonl",
      format: "jsonl",                    # only jsonl in Phase 1c
      chunk_size_lines: 1000              # optional; default 1000
    }

`index()` walks the JSONL file once, recording byte offsets at every
`chunk_size_lines`-th line boundary. Each emitted PayloadRef carries a
byte_range so `read()` can stream just that chunk without loading the
whole file.

The connector ignores credentials — local files don't need them.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from tandemn_user_data.core.record import NormalizedRecord, OutputRef, PayloadRef

DEFAULT_CHUNK_SIZE_LINES = 1000


class LocalFileConnector:
    """Reference connector for JSONL on the local filesystem."""

    type = "local"

    # ----- input ----------------------------------------------------------

    def index(
        self,
        source_spec: dict[str, Any],
        creds: Any | None = None,  # noqa: ARG002 — local doesn't need creds
    ) -> Iterator[PayloadRef]:
        uri = source_spec["uri"]
        fmt = source_spec.get("format", "jsonl")
        if fmt != "jsonl":
            raise NotImplementedError(
                f"LocalFileConnector only supports format='jsonl', got {fmt!r}"
            )
        chunk_size = int(source_spec.get("chunk_size_lines", DEFAULT_CHUNK_SIZE_LINES))
        if chunk_size <= 0:
            raise ValueError("chunk_size_lines must be > 0")

        path = Path(uri)
        if not path.is_file():
            raise FileNotFoundError(f"input source not found: {path}")

        # Walk the file once, recording (start, end) byte ranges every
        # `chunk_size` lines. The end is exclusive on read.
        with path.open("rb") as f:
            start = 0
            line_count = 0
            while True:
                line = f.readline()
                if not line:
                    # final partial chunk if any
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
        creds: Any | None = None,  # noqa: ARG002 — local doesn't need creds
    ) -> Iterator[NormalizedRecord]:
        if payload_ref.type != self.type:
            raise ValueError(
                f"LocalFileConnector cannot read payload_ref of type {payload_ref.type!r}"
            )
        if payload_ref.format != "jsonl":
            raise NotImplementedError(
                f"LocalFileConnector only supports format='jsonl', got {payload_ref.format!r}"
            )

        path = Path(payload_ref.uri)
        start, end = payload_ref.byte_range or (0, os.path.getsize(path))

        with path.open("rb") as f:
            f.seek(start)
            buf = f.read(end - start)

        for raw in buf.splitlines():
            if not raw.strip():
                continue
            row = json.loads(raw)
            yield NormalizedRecord(
                input_id=str(row.get("input_id") or row.get("id") or ""),
                tenant_id=str(row.get("tenant_id") or ""),
                job_id=str(row.get("job_id") or ""),
                prompt=row.get("prompt", ""),
                metadata=row.get("metadata", {}) or {},
            )

    # ----- output ---------------------------------------------------------

    def write(
        self,
        output_ref: OutputRef,
        records: Iterable[NormalizedRecord],
        creds: Any | None = None,  # noqa: ARG002 — local doesn't need creds
    ) -> int:
        if output_ref.type != self.type:
            raise ValueError(
                f"LocalFileConnector cannot write output_ref of type {output_ref.type!r}"
            )
        if output_ref.format != "jsonl":
            raise NotImplementedError(
                f"LocalFileConnector only supports format='jsonl', got {output_ref.format!r}"
            )

        path = Path(output_ref.uri)
        path.parent.mkdir(parents=True, exist_ok=True)

        count = 0
        with path.open("ab") as f:
            for rec in records:
                f.write(rec.model_dump_json().encode("utf-8"))
                f.write(b"\n")
                count += 1
        return count
