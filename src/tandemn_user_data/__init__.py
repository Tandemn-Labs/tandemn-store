"""tandemn_user_data — user payloads in motion (Orca + workers + CLI).

Owns PayloadRef / OutputRef / NormalizedRecord, the connector protocols
and reference connectors, WorkerClient, the Orca-side indexer, and the
worker-side credential resolver.

Must NOT import tandemn_system_data: this package runs on customer GPU
nodes and the boundary is enforced by import-linter.
"""

__version__ = "0.1.0"
