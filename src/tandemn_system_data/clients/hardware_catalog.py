"""Hardware catalog — Orca's latest cloud hardware/pricing snapshot in Postgres."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from tandemn_system_data.clients.postgres import PostgresClient
from tandemn_system_data.db.orm import HardwareCatalogRow
from tandemn_system_data.models._base import utc_now
from tandemn_system_data.models.hardware_catalog import (
    DEFAULT_HARDWARE_CATALOG_KEY,
    HardwareCatalog,
)


class HardwareCatalogStore:
    """One row per ``catalog_key``. Orca ``replace``s; consumers ``get``."""

    def __init__(self, client: PostgresClient) -> None:
        self._client = client

    def get(self, catalog_key: str = DEFAULT_HARDWARE_CATALOG_KEY) -> HardwareCatalog | None:
        with self._client.session() as s:
            row = s.get(HardwareCatalogRow, catalog_key)
            if row is None:
                return None
            return HardwareCatalog(
                catalog_key=row.catalog_key,
                updated_at=row.updated_at,
                catalog=row.catalog,
            )

    def all(self) -> list[HardwareCatalog]:
        """Return every seeded cloud catalog for multi-cloud resolution."""
        with self._client.session() as s:
            rows = s.scalars(select(HardwareCatalogRow).order_by(HardwareCatalogRow.catalog_key)).all()
            return [
                HardwareCatalog(catalog_key=row.catalog_key, updated_at=row.updated_at, catalog=row.catalog)
                for row in rows
            ]

    def replace(
        self,
        catalog: dict[str, Any],
        catalog_key: str = DEFAULT_HARDWARE_CATALOG_KEY,
    ) -> HardwareCatalog:
        now = utc_now()
        stmt = (
            insert(HardwareCatalogRow)
            .values(catalog_key=catalog_key, updated_at=now, catalog=catalog)
            .on_conflict_do_update(
                index_elements=[HardwareCatalogRow.catalog_key],
                set_={"updated_at": now, "catalog": catalog},
            )
            .returning(HardwareCatalogRow)
        )
        with self._client.begin() as s:
            row = s.scalars(stmt).one()
        return HardwareCatalog(
            catalog_key=row.catalog_key,
            updated_at=row.updated_at,
            catalog=row.catalog,
        )
