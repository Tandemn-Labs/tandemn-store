"""Core user-data types — DATA_ARCHITECTURE.md §7.

Exactly three type-level constructs flow through the user-data path:

  PayloadRef       = where to read a single chunk from
  OutputRef        = where to write chunk outputs to
  NormalizedRecord = the shape every chunk record takes once it has been
                     read by a connector and is in flight to a worker /
                     vLLM / output sink

The connector framework (tandemn_user_data/connectors/) is the only
place that knows about source-specific URIs (s3://, snowflake://, ...).
Everything downstream sees only NormalizedRecords and these refs.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class _UserDataModel(BaseModel):
    """All user-data types forbid extras to keep the wire format tight."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
        from_attributes=True,
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------------------------
# PayloadRef / OutputRef (§7)
# ---------------------------------------------------------------------------


class PayloadRef(_UserDataModel):
    """A pointer to one chunk of user input.

    Fields:
      type             connector type ("local", "s3", "snowflake", ...)
      uri              source-specific location (file path, s3:// URI, ...)
      byte_range       optional [start, end] for blob sources; whole object if None
      format           wire format of the bytes ("jsonl", "parquet", ...)
      credentials_ref  pointer to a short-lived, scoped credential in the
                       credentials store; resolved by the worker at fetch time
    """

    type: str
    uri: str
    byte_range: tuple[int, int] | None = None
    format: str = "jsonl"
    credentials_ref: str | None = None


class OutputRef(_UserDataModel):
    """A pointer to where a chunk's outputs should be written.

    Same shape as PayloadRef minus byte_range (outputs append; they don't
    target an offset).
    """

    type: str
    uri: str
    format: str = "jsonl"
    credentials_ref: str | None = None


# ---------------------------------------------------------------------------
# NormalizedRecord (§7)
# ---------------------------------------------------------------------------


class NormalizedRecord(_UserDataModel):
    """The uniform shape every chunk record takes inside Tandemn.

    Connectors translate source-specific rows (S3 JSONL lines, Snowflake
    cursors, BigQuery rows, ...) into NormalizedRecords. From this point
    on, the rest of Tandemn is source-agnostic.

    Fields:
      input_id    stable per-record ID (connector-supplied or derived)
      user_id   canonical user ID (from tandemn_system_data.ids); the
                  worker sees it but does not validate against Postgres
      job_id      canonical job ID
      prompt      the actual text to feed vLLM
      metadata    free-form per-record metadata carried alongside the prompt
    """

    input_id: str
    user_id: str
    job_id: str
    prompt: str
    metadata: dict[str, Any] = Field(default_factory=dict)
