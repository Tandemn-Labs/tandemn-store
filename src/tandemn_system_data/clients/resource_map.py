"""Resource map APIs — Orca's in-memory view of reservable capacity.

Three pieces, one per side of the contract:

  ResourceMapStore        Orca-side holder. Single writer (the
                          reconciler) bumps `version` on every replace;
                          readers get immutable-by-convention snapshots.
  create_resource_map_app Mounts GET /resource-map. In production this
                          folds into Orca's main FastAPI app.
  ResourceMapClient       Koi-side reader over HTTP.

No table, no persistence: per DATA_ARCHITECTURE.md §6 the resource map
is not canonical state. If Orca goes multi-replica, the store moves to
a Postgres JSONB row behind the same three interfaces.

No auth: Koi and Orca are both control-plane services inside the trust
boundary. Workers never call this endpoint (unlike /credentials, which
faces untrusted GPU nodes and requires a token).
"""

from __future__ import annotations

import threading

import httpx
from fastapi import FastAPI

from tandemn_system_data.models.resource_map import ResourceMap, ResourcePool


class ResourceMapStore:
    """Thread-safe single-writer holder for the live ResourceMap.

    Readers MUST treat snapshots as immutable: build new pools and
    replace(), never mutate a snapshot in place.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._map = ResourceMap()

    def get(self) -> ResourceMap:
        return self._map

    def replace(self, pools: dict[str, dict[str, ResourcePool]]) -> ResourceMap:
        """Publish a new snapshot with a bumped version. Returns it."""
        with self._lock:
            new = ResourceMap(version=self._map.version + 1, pools=pools)
            self._map = new
            return new


def create_resource_map_app(store: ResourceMapStore) -> FastAPI:
    """Build a minimal FastAPI app exposing GET /resource-map."""
    app = FastAPI(title="tandemn-resource-map", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/resource-map")
    def get_resource_map() -> ResourceMap:
        return store.get()

    return app


class ResourceMapClient:
    """Koi-side reader: GET /resource-map from Orca."""

    def __init__(self, base_url: str, *, timeout: float = 5.0) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def get(self) -> ResourceMap:
        resp = httpx.get(f"{self._base_url}/resource-map", timeout=self._timeout)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"resource-map endpoint returned {resp.status_code}: {resp.text[:200]}"
            )
        return ResourceMap.model_validate(resp.json())
