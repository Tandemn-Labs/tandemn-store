"""Resource map — Orca's live view of reservable capacity in Postgres."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert

from tandemn_system_data.clients.postgres import PostgresClient
from tandemn_system_data.db.orm import ResourceMapRow
from tandemn_system_data.models._base import utc_now
from tandemn_system_data.models.resource_map import ResourceMap, ResourcePool


def _pools_to_json(pools: dict[str, dict[str, ResourcePool]]) -> dict[str, Any]:
    return {
        provider: {
            instance_type: pool.model_dump(mode="json") for instance_type, pool in by_type.items()
        }
        for provider, by_type in pools.items()
    }


def _pools_from_json(raw: dict[str, Any]) -> dict[str, dict[str, ResourcePool]]:
    return {
        provider: {
            instance_type: ResourcePool.model_validate(pool)
            for instance_type, pool in by_type.items()
        }
        for provider, by_type in raw.items()
    }


def _row_to_model(row: ResourceMapRow) -> ResourceMap:
    return ResourceMap(
        version=row.version,
        updated_at=row.updated_at,
        pools=_pools_from_json(row.pools_json),
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

    def replace(self, pools: dict[str, dict[str, ResourcePool]]) -> ResourceMap:
        """Publish a new snapshot with a bumped version."""
        pools_json = _pools_to_json(pools)
        now = utc_now()
        stmt = (
            insert(ResourceMapRow)
            .values(
                user_id=self._user_id,
                version=1,
                pools_json=pools_json,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[ResourceMapRow.user_id],
                set_={
                    "version": ResourceMapRow.version + 1,
                    "pools_json": pools_json,
                    "updated_at": now,
                },
            )
            .returning(ResourceMapRow)
        )
        with self._client.begin() as s:
            row = s.scalars(stmt).one()
        return _row_to_model(row)
