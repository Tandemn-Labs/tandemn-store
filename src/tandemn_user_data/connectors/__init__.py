"""Connectors — DATA_ARCHITECTURE.md §7.

Adding a new connector is one PR (principle 6): drop a module here that
implements the InputConnector / OutputConnector protocols, then register
it in your application's ConnectorRegistry.
"""

from __future__ import annotations

from tandemn_user_data.connectors.s3 import S3Connector

__all__ = ["S3Connector"]
