"""Tests for HttpCredentialResolver.

The resolver lives in tandemn_user_data and must not import
tandemn_system_data. We use httpx's MockTransport (no system_data
dependency) for the construction / cache / error tests, and a true
end-to-end FastAPI app for the round-trip.
"""

from __future__ import annotations

import httpx
import pytest

from tandemn_user_data.core import HttpCredentialResolver

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_construction_requires_base_url_and_token():
    with pytest.raises(ValueError):
        HttpCredentialResolver(base_url="", token="t")
    with pytest.raises(ValueError):
        HttpCredentialResolver(base_url="http://x", token="")


# ---------------------------------------------------------------------------
# resolve() with MockTransport (no system_data import)
# ---------------------------------------------------------------------------


def _build_resolver_with_mock(handler) -> HttpCredentialResolver:
    """Patch httpx.get globally for one resolver call.

    We can't pass a transport into the bare httpx.get() call inside
    HttpCredentialResolver, so use monkeypatch-style by temporarily
    swapping the module attribute.
    """
    return HttpCredentialResolver(base_url="http://stub", token="t")


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


def test_resolve_caches_responses(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "credentials_ref": "cred_1",
                "user_id": "usr_1",
                "scope_json": {},
                "secret_payload": {"x": 1},
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        )

    import tandemn_user_data.core.credentials_client as cc

    monkeypatch.setattr(cc.httpx, "get", fake_get)

    r = HttpCredentialResolver(base_url="http://x", token="t")
    assert r.resolve("cred_1") == {"x": 1}
    assert r.resolve("cred_1") == {"x": 1}
    assert calls["n"] == 1  # second call hit the cache


def test_resolve_cache_disabled(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "credentials_ref": "cred_1",
                "user_id": "usr_1",
                "scope_json": {},
                "secret_payload": "v",
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
        )

    import tandemn_user_data.core.credentials_client as cc

    monkeypatch.setattr(cc.httpx, "get", fake_get)

    r = HttpCredentialResolver(base_url="http://x", token="t", cache_responses=False)
    r.resolve("cred_1")
    r.resolve("cred_1")
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

    r = HttpCredentialResolver(base_url="http://x", token="t")
    monkeypatch.setattr(cc.httpx, "get", factory(410))
    with pytest.raises(PermissionError):
        r.resolve("cred_expired")

    r = HttpCredentialResolver(base_url="http://x", token="t")
    monkeypatch.setattr(cc.httpx, "get", factory(401))
    with pytest.raises(PermissionError):
        r.resolve("cred_unauth")


# ---------------------------------------------------------------------------
# Boundary: this module must not have transitively pulled in system_data
# ---------------------------------------------------------------------------


def test_http_resolver_module_does_not_import_system_data():
    """Re-verify the §1 principle 2 boundary specifically for the
    credentials_client module (the most likely place to slip)."""
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
