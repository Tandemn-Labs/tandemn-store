"""HardwareCatalog — latest cloud hardware/pricing snapshot.

One Postgres row per ``catalog_key`` in ``hardware_catalogs``. Orca writes
the latest AWS accelerated-hardware catalog; other scripts read it instead of
calling AWS. ``catalog`` is the structured JSON object as fetched.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.models._base import CanonicalModel, utc_now

DEFAULT_HARDWARE_CATALOG_KEY = "aws-accelerated-hardware-v2"


class HardwareCatalog(CanonicalModel):
    catalog_key: str = DEFAULT_HARDWARE_CATALOG_KEY
    updated_at: datetime = Field(default_factory=utc_now)
    catalog: dict[str, Any] = Field(default_factory=dict)
