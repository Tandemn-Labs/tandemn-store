"""Model catalog — per-model architecture/engine/tuning defaults in Postgres."""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert

from tandemn_system_data.clients.postgres import PostgresClient
from tandemn_system_data.db.orm import ModelCatalogRow
from tandemn_system_data.models._base import utc_now
from tandemn_system_data.models.model_catalog import (
    DEFAULT_MIN_CHAIN_WARMUP_MINUTES,
    ModelCatalog,
    model_catalog_from_row,
    model_catalog_to_json,
)


def _to_model(row: ModelCatalogRow) -> ModelCatalog:
    return model_catalog_from_row(
        model_id=row.model_id, updated_at=row.updated_at, catalog=row.catalog_json
    )


class ModelCatalogStore:
    """One row per model id. Whoever populates it (Orca script, human) ``replace``s;
    Orca's compiler / Koi's rank sizing ``get``.
    """

    def __init__(self, client: PostgresClient) -> None:
        self._client = client

    def get(self, model_id: str) -> ModelCatalog | None:
        with self._client.session() as s:
            row = s.get(ModelCatalogRow, model_id)
            return _to_model(row) if row else None

    def replace(self, catalog: ModelCatalog) -> ModelCatalog:
        """Publish a new snapshot for ``catalog.model_id``."""
        now = utc_now()
        catalog_json = model_catalog_to_json(catalog)
        stmt = (
            insert(ModelCatalogRow)
            .values(model_id=catalog.model_id, updated_at=now, catalog_json=catalog_json)
            .on_conflict_do_update(
                index_elements=[ModelCatalogRow.model_id],
                set_={"updated_at": now, "catalog_json": catalog_json},
            )
            .returning(ModelCatalogRow)
        )
        with self._client.begin() as s:
            row = s.scalars(stmt).one()
        return _to_model(row)

    def get_min_chain_warmup_minutes(self, model_id: str) -> float:
        """The model's cold-start floor, in minutes.

        Defaults to DEFAULT_MIN_CHAIN_WARMUP_MINUTES when the model has no
        catalog row yet, so callers never need a None-check.
        """
        catalog = self.get(model_id)
        return catalog.min_chain_warmup_time if catalog else DEFAULT_MIN_CHAIN_WARMUP_MINUTES

    def set_min_chain_warmup_minutes(self, model_id: str, minutes: float) -> ModelCatalog:
        """Patch just the cold-start floor, preserving the rest of the catalog."""
        catalog = self.get(model_id) or ModelCatalog(model_id=model_id)
        catalog.min_chain_warmup_time = minutes
        return self.replace(catalog)
