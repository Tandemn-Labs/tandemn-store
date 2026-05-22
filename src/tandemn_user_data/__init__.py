"""tandemn_user_data — user payloads in motion (Orca + workers + CLI).

This package owns:
  - NormalizedRecord / PayloadRef / OutputRef types
  - InputConnector / OutputConnector protocols
  - Reference connectors (LocalFileConnector, S3Connector)
  - Worker-side fetch_payload / write_outputs
  - Orca-side indexer + credentials_issuer

Imported by Orca, workers, and CLI. Does NOT import tandemn_system_data.
"""

__version__ = "0.1.0"
