"""Tests for HttpCredentialResolver.

Uses monkeypatched httpx.get; the full round-trip against a live
credentials server is in test_credentials_e2e.py.
"""

from __future__ import annotations

import httpx
import pytest

from tandemn_user_data.core import HttpCredentialResolver


def test_construction_requires_base_url_and_token():
    with pytest.raises(ValueError):
        HttpCredentialResolver(base_url="", token="t")
    with pytest.raises(ValueError):
        HttpCredentialResolver(base_url="http://x", token="")


def test_resolve_returns_none_for_none_ref():
    r = HttpCredentialResolver(base_url="http://x", token="t")
    assert r.resolve(None) is None


def test_resolve_round_trips_secret_payload(monkeypatch):
    captured: dict[str, str] = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["header"] = headers["X-Tandemn-Worker-Token"]
        return httpx.Response(
            200,
            json={
                "credentials_ref": "cred_1",
                "user_id": "usr_1",
                "scope_json": {},
                "secret_payload": {"access_key": "k", "secret_key": "s"},
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        )

    import tandemn_user_data.core.credentials_client as cc

    monkeypatch.setattr(cc.httpx, "get", fake_get)

    r = HttpCredentialResolver(base_url="http://orca.internal", token="worker-tok")
    out = r.resolve("cred_1")
    assert out == {"access_key": "k", "secret_key": "s"}
    assert captured["url"] == "http://orca.internal/credentials/cred_1"
    assert captured["header"] == "worker-tok"


def test_resolve_never_caches(monkeypatch):
    """Credentials are short-lived; every resolve must hit the server so
    expiry (410) is enforced server-side."""
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return httpx.Response(
            200,
            json={"secret_payload": {"x": calls["n"]}},
        )

    import tandemn_user_data.core.credentials_client as cc

    monkeypatch.setattr(cc.httpx, "get", fake_get)

    r = HttpCredentialResolver(base_url="http://x", token="t")
    assert r.resolve("cred_1") == {"x": 1}
    assert r.resolve("cred_1") == {"x": 2}
    assert calls["n"] == 2


def test_resolve_translates_status_codes(monkeypatch):
    import tandemn_user_data.core.credentials_client as cc

    def factory(status: int):
        def fake_get(url, headers=None, timeout=None):
            return httpx.Response(status)

        return fake_get

    r = HttpCredentialResolver(base_url="http://x", token="t")

    monkeypatch.setattr(cc.httpx, "get", factory(404))
    with pytest.raises(KeyError):
        r.resolve("cred_missing")

    monkeypatch.setattr(cc.httpx, "get", factory(410))
    with pytest.raises(PermissionError):
        r.resolve("cred_expired")

    monkeypatch.setattr(cc.httpx, "get", factory(401))
    with pytest.raises(PermissionError):
        r.resolve("cred_unauth")


def test_http_resolver_module_does_not_import_system_data():
    """§1 principle 2 boundary for the most likely place to slip."""
    import importlib

    mod = importlib.import_module("tandemn_user_data.core.credentials_client")
    for name in dir(mod):
        try:
            obj = getattr(mod, name)
        except Exception:
            continue
        obj_module = getattr(obj, "__module__", None)
        assert not (obj_module and obj_module.startswith("tandemn_system_data")), (
            f"{name!r} originates in {obj_module}"
        )
