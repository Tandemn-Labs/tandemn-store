"""Tests for the resource map APIs: store (Orca writes), app (Orca
serves), client (Koi reads). No infrastructure required."""

from __future__ import annotations

import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from tandemn_system_data.clients import (
    ResourceMapClient,
    ResourceMapStore,
    create_resource_map_app,
)
from tandemn_system_data.models import ResourceMap, ResourcePool


def _pools(available: int) -> dict[str, dict[str, ResourcePool]]:
    return {"aws": {"g6e.12xlarge": ResourcePool(total=8, available=available)}}


# ----- store -----------------------------------------------------------------


def test_store_starts_empty_at_version_zero():
    store = ResourceMapStore()
    snapshot = store.get()
    assert snapshot.version == 0
    assert snapshot.pools == {}


def test_replace_bumps_version_and_publishes():
    store = ResourceMapStore()
    first = store.replace(_pools(available=3))
    second = store.replace(_pools(available=2))

    assert (first.version, second.version) == (1, 2)
    assert store.get() is second
    assert second.updated_at >= first.updated_at


def test_replace_is_thread_safe_versions_never_collide():
    store = ResourceMapStore()
    n_threads, per_thread = 8, 50

    def writer():
        for _ in range(per_thread):
            store.replace(_pools(available=1))

    threads = [threading.Thread(target=writer) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every replace must have gotten a unique version.
    assert store.get().version == n_threads * per_thread


# ----- app + client ----------------------------------------------------------


def test_endpoint_serves_current_snapshot():
    store = ResourceMapStore()
    store.replace(_pools(available=3))
    client = TestClient(create_resource_map_app(store))

    resp = client.get("/resource-map")
    assert resp.status_code == 200
    rm = ResourceMap.model_validate(resp.json())
    assert rm.version == 1
    assert rm.pools["aws"]["g6e.12xlarge"].available == 3

    store.replace(_pools(available=2))
    assert client.get("/resource-map").json()["version"] == 2


def test_client_round_trips_through_real_http_layer(monkeypatch):
    """ResourceMapClient against the app via httpx transport."""
    store = ResourceMapStore()
    store.replace(_pools(available=5))
    app_client = TestClient(create_resource_map_app(store))

    def fake_get(url, timeout=None):
        assert url == "http://orca/resource-map"
        return app_client.get("/resource-map")

    import tandemn_system_data.clients.resource_map as rm_module

    monkeypatch.setattr(rm_module.httpx, "get", fake_get)

    rm = ResourceMapClient("http://orca").get()
    assert rm.version == 1
    assert rm.pools["aws"]["g6e.12xlarge"].total == 8


def test_client_requires_base_url_and_raises_on_error(monkeypatch):
    with pytest.raises(ValueError):
        ResourceMapClient("")

    import tandemn_system_data.clients.resource_map as rm_module

    monkeypatch.setattr(
        rm_module.httpx, "get", lambda url, timeout=None: httpx.Response(500, text="boom")
    )
    with pytest.raises(RuntimeError):
        ResourceMapClient("http://orca").get()
