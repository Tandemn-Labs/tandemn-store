"""Unit tests for tandemn_user_data.core.

Anchors:
  - DATA_ARCHITECTURE.md §1 principle 2 (two libraries)
  - DATA_ARCHITECTURE.md §1 principle 3 (workers are dumb)
  - DATA_ARCHITECTURE.md §7 (PayloadRef / OutputRef / NormalizedRecord)
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest
from pydantic import ValidationError

import tandemn_user_data
from tandemn_user_data.core import (
    ConnectorRegistry,
    InputConnector,
    NormalizedRecord,
    NullResolver,
    OutputConnector,
    OutputRef,
    PayloadRef,
)

# ---------------------------------------------------------------------------
# Type-level constructs (§7)
# ---------------------------------------------------------------------------


def test_payload_ref_minimum_fields():
    ref = PayloadRef(type="local", uri="/tmp/inputs.jsonl")
    assert ref.type == "local"
    assert ref.format == "jsonl"  # default
    assert ref.byte_range is None
    assert ref.credentials_ref is None


def test_payload_ref_full_shape():
    ref = PayloadRef(
        type="s3",
        uri="s3://customer/inputs/x.jsonl",
        byte_range=(0, 4096),
        format="jsonl",
        credentials_ref="cred_abc",
    )
    assert ref.byte_range == (0, 4096)
    assert ref.credentials_ref == "cred_abc"


def test_output_ref_has_no_byte_range_field():
    """OutputRef intentionally omits byte_range per §7."""
    ref = OutputRef(type="s3", uri="s3://customer/outputs/", credentials_ref="cred_abc")
    assert not hasattr(ref, "byte_range") or "byte_range" not in ref.model_fields


def test_normalized_record_required_fields():
    rec = NormalizedRecord(
        input_id="in_1",
        user_id="usr_1",
        job_id="job_1",
        prompt="hello world",
    )
    assert rec.metadata == {}


def test_all_models_forbid_extras():
    with pytest.raises(ValidationError):
        PayloadRef(type="local", uri="/tmp/x", bogus="nope")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        OutputRef(type="local", uri="/tmp/x", bogus="nope")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        NormalizedRecord(
            input_id="i",
            user_id="t",
            job_id="j",
            prompt="p",
            bogus="nope",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# Connector protocols + registry (§7)
# ---------------------------------------------------------------------------


class _FakeConnector:
    """Implements both InputConnector and OutputConnector protocols."""

    type = "fake"

    def index(self, source_spec, creds=None):
        for i in range(2):
            yield PayloadRef(type=self.type, uri=f"fake://{i}")

    def read(self, payload_ref, creds=None):
        yield NormalizedRecord(input_id="i", user_id="t", job_id="j", prompt="p")

    def write(self, output_ref, records, creds=None):
        return sum(1 for _ in records)


def test_registry_register_and_lookup():
    reg = ConnectorRegistry()
    conn = _FakeConnector()
    reg.register(conn)
    assert reg.input_for("fake") is conn
    assert reg.output_for("fake") is conn
    assert reg.known_input_types() == ["fake"]
    assert reg.known_output_types() == ["fake"]


def test_registry_rejects_unknown_type():
    reg = ConnectorRegistry()
    with pytest.raises(KeyError):
        reg.input_for("nope")
    with pytest.raises(KeyError):
        reg.output_for("nope")


def test_protocols_runtime_checkable():
    """isinstance() works against the Protocols so the registry can
    auto-detect dual-role connectors."""
    conn = _FakeConnector()
    assert isinstance(conn, InputConnector)
    assert isinstance(conn, OutputConnector)


# ---------------------------------------------------------------------------
# Credential resolvers (§7)
# ---------------------------------------------------------------------------


def test_null_resolver_returns_none():
    assert NullResolver().resolve("any_ref") is None
    assert NullResolver().resolve(None) is None


# ---------------------------------------------------------------------------
# Boundary: tandemn_user_data must NEVER import tandemn_system_data (§1, §2)
# ---------------------------------------------------------------------------


def test_user_data_does_not_import_system_data():
    """Hard boundary check: walk every module under tandemn_user_data
    and assert that none of them transitively import tandemn_system_data."""
    failures: list[str] = []

    pkg = tandemn_user_data
    for modinfo in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
        mod = importlib.import_module(modinfo.name)
        # Walk every binding in the module and check its module of origin.
        for name in dir(mod):
            try:
                obj = getattr(mod, name)
            except Exception:
                continue
            obj_module = getattr(obj, "__module__", None)
            if obj_module and obj_module.startswith("tandemn_system_data"):
                failures.append(
                    f"{modinfo.name} exposes {name!r} from {obj_module} (violates §1 principle 2)"
                )

    assert not failures, "\n".join(failures)
