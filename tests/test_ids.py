"""Unit tests for the canonical ID generator."""

from __future__ import annotations

import pytest

from tandemn_system_data import ids


def test_new_id_has_correct_prefix_and_length():
    job_id = ids.new_id("job")
    assert job_id.startswith("job_")
    # "job_" + 26-char ULID
    assert len(job_id) == 4 + 26


def test_per_kind_helpers_use_registered_prefixes():
    pairs = [
        (ids.new_user_id(), "usr_"),
        (ids.new_resource_map_id(), "rmap_"),
        (ids.new_job_id(), "job_"),
        (ids.new_decision_id(), "dec_"),
        (ids.new_placement_alternative_id(), "alt_"),
        (ids.new_chain_id(), "chain_"),
        (ids.new_attempt_id(), "att_"),
        (ids.new_event_id(), "evt_"),
        (ids.new_outcome_id(), "out_"),
        (ids.new_credentials_ref(), "cred_"),
    ]
    for value, expected_prefix in pairs:
        assert value.startswith(expected_prefix), value


def test_ids_are_unique():
    seen = {ids.new_job_id() for _ in range(1_000)}
    assert len(seen) == 1_000


def test_ids_are_time_ordered():
    # ULIDs have ms-resolution time prefix, so back-to-back ids should
    # sort the same way they were generated.
    ordered = [ids.new_job_id() for _ in range(50)]
    assert ordered == sorted(ordered)


def test_kind_of_round_trip():
    assert ids.kind_of(ids.new_job_id()) == "job"
    assert ids.kind_of(ids.new_placement_alternative_id()) == "placement_alternative"
    assert ids.kind_of(ids.new_credentials_ref()) == "credentials"


def test_kind_of_rejects_unknown_prefix():
    with pytest.raises(ValueError):
        ids.kind_of("xyz_01J9DEADBEEFDEADBEEFDEADBE")


def test_is_valid_id_structural():
    job_id = ids.new_job_id()
    assert ids.is_valid_id(job_id)
    assert ids.is_valid_id(job_id, kind="job")
    assert not ids.is_valid_id(job_id, kind="chain")
    assert not ids.is_valid_id("job_tooshort")
    assert not ids.is_valid_id("no-underscore")
    assert not ids.is_valid_id("xyz_01J9DEADBEEFDEADBEEFDEADBE")


def test_new_id_rejects_unknown_kind():
    with pytest.raises(ValueError):
        ids.new_id("nonexistent")  # type: ignore[arg-type]


def test_theory_prefix_reserved_but_no_helper():
    # `theory` is reserved for future use; the prefix is registered
    # but there is no per-kind helper (DATA_ARCHITECTURE.md §11).
    assert "theory" in ids.PREFIXES
    assert not hasattr(ids, "new_theory_id")
    # new_id("theory") still works since the prefix is registered.
    t = ids.new_id("theory")
    assert t.startswith("thry_")
