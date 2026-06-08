"""Orca-side helpers — DATA_ARCHITECTURE.md §7.

indexer.index_source wraps a connector's index() for Orca.
"""

from __future__ import annotations

from tandemn_user_data.orca.indexer import index_source, index_source_to_list

__all__ = [
    "index_source",
    "index_source_to_list",
]
