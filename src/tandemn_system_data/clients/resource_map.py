"""Resource map — Orca's live view of reservable capacity in Postgres."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert

from tandemn_system_data.clients.postgres import PostgresClient
from tandemn_system_data.db.orm import ResourceMapRow
from tandemn_system_data.models._base import utc_now
from tandemn_system_data.models.resource_map import Cloud, ResourceMap


def _body_to_json(resource_map: ResourceMap) -> dict[str, Any]:
    return {
        "market": list(resource_map.market),
        "clouds": {
            cloud_id: cloud.model_dump(mode="json")
            for cloud_id, cloud in resource_map.clouds.items()
        },
    }


def _body_from_json(raw: dict[str, Any]) -> tuple[list[str], dict[str, Cloud]]:
    if "clouds" in raw:
        market = list(raw.get("market") or ["reserved"])
        clouds = {
            cloud_id: Cloud.model_validate(cloud_body)
            for cloud_id, cloud_body in (raw.get("clouds") or {}).items()
        }
        return market, clouds
    # Legacy flat pools[provider][instance_type] -> {total, metadata}
    return _legacy_flat_pools_to_clouds(raw)


def _legacy_flat_pools_to_clouds(raw: dict[str, Any]) -> tuple[list[str], dict[str, Cloud]]:
    tree: dict[str, Any] = {}
    for provider, by_type in raw.items():
        if not isinstance(by_type, dict):
            continue
        for instance_type, pool in by_type.items():
            if not isinstance(pool, dict) or "total" not in pool:
                continue
            meta = pool.get("metadata") or {}
            region_id = str(meta.get("region") or "default")
            zone_id = str(meta.get("zone") or "default")
            gpu_type = str(meta.get("gpu_type") or instance_type)
            gpus_per = int(meta.get("gpus_per_instance") or 1)
            total_gpus = int(pool.get("total") or 0)
            total_instances = total_gpus // gpus_per if gpus_per else 0
            cloud_body = tree.setdefault(provider, {"regions": {}})
            region_body = cloud_body["regions"].setdefault(region_id, {"zones": {}})
            zone_body = region_body["zones"].setdefault(zone_id, {"network_fabrics": {}})
            fabric_body = zone_body["network_fabrics"].setdefault(
                "default",
                {"fabric_type": str(meta.get("fabric_type") or "default"), "machine_pools": {}},
            )
            fabric_body["machine_pools"][instance_type] = {
                "instance_family": meta.get("instance_family"),
                "gpu_type": gpu_type,
                "gpus_per_instance": gpus_per,
                "total_instances": total_instances,
                "price_per_instance_hour": meta.get("price_per_instance_hour"),
            }
    clouds = {cloud_id: Cloud.model_validate(body) for cloud_id, body in tree.items()}
    return ["reserved"], clouds


def _row_to_model(row: ResourceMapRow) -> ResourceMap:
    market, clouds = _body_from_json(row.pools_json)
    return ResourceMap(
        version=row.version,
        updated_at=row.updated_at,
        market=market,
        clouds=clouds,
    )


class ResourceMapStore:
    """One live ``ResourceMap`` row per user. Orca ``replace``s; Koi ``get``s."""

    def __init__(self, client: PostgresClient, *, user_id: str) -> None:
        self._client = client
        self._user_id = user_id

    def get(self) -> ResourceMap:
        with self._client.session() as s:
            row = s.get(ResourceMapRow, self._user_id)
            if row is None:
                return ResourceMap()
            return _row_to_model(row)

    def replace(self, resource_map: ResourceMap) -> ResourceMap:
        """Publish a new snapshot with a bumped version."""
        body_json = _body_to_json(resource_map)
        now = utc_now()
        stmt = (
            insert(ResourceMapRow)
            .values(
                user_id=self._user_id,
                version=1,
                pools_json=body_json,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[ResourceMapRow.user_id],
                set_={
                    "version": ResourceMapRow.version + 1,
                    "pools_json": body_json,
                    "updated_at": now,
                },
            )
            .returning(ResourceMapRow)
        )
        with self._client.begin() as s:
            row = s.scalars(stmt).one()
        return _row_to_model(row)
