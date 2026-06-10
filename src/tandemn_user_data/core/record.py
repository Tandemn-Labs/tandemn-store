"""Core user-data types — DATA_ARCHITECTURE.md §7.

PayloadRef / OutputRef / NormalizedRecord are the only shapes that flow
through the user-data path. Connectors are the only code that knows
source-specific URIs; everything downstream sees these three types.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _UserDataModel(BaseModel):
    """All user-data types forbid extras to keep the wire format tight."""

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        str_strip_whitespace=True,
    )


class PayloadRef(_UserDataModel):
    """Pointer to one chunk of user input.

    byte_range is [start, end) — exclusive end. None means whole object.
    credentials_ref is resolved by the worker at fetch time; never a secret.
    """

    type: str
    uri: str
    byte_range: tuple[int, int] | None = None
    format: str = "jsonl"
    credentials_ref: str | None = None


class OutputRef(_UserDataModel):
    """Pointer to where chunk outputs are written. Outputs append; no byte_range."""

    type: str
    uri: str
    format: str = "jsonl"
    credentials_ref: str | None = None


class NormalizedRecord(_UserDataModel):
    """The uniform record shape inside Tandemn, whatever the source format."""

    input_id: str
    user_id: str
    job_id: str
    prompt: str
    metadata: dict[str, Any] = Field(default_factory=dict)
