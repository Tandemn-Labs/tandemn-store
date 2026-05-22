"""Reference and future connectors — DATA_ARCHITECTURE.md §7.

Adding a new connector is one PR (principle 6): drop a module here that
exposes both InputConnector and OutputConnector behaviour, then register
it in your application's ConnectorRegistry.
"""

from __future__ import annotations

from tandemn_user_data.connectors.local import LocalFileConnector

__all__ = ["LocalFileConnector"]
