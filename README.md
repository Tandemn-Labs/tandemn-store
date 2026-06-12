# tandemn-store

Canonical data layer for Tandemn (Orca + Koi + workers).

Ships two packages:

- **`tandemn_system_data`** — canonical state (Postgres spine, Postgres event log, credentials store/server). Imported by **Orca and Koi only**.
- **`tandemn_user_data`** — user payloads in motion (connectors, credential resolver, `PayloadRef` / `OutputRef` / `NormalizedRecord`). Imported by **Orca, workers, and CLI**.

The architecture and rationale live in [`DATA_ARCHITECTURE.md`](./DATA_ARCHITECTURE.md).

---

## What's here

**`tandemn_system_data`**
- Canonical IDs (`ids.py`), Pydantic models, typed event payload registry (`events.py`)
- SQLAlchemy ORM mirroring DATA_ARCHITECTURE.md §5 + Alembic migrations
- `PostgresClient`, `PostgresEventLog` (append events, read by cursor, `event_consumer_offsets`)
- `JobStore` — Orca writes (submit, CAS status transitions, gang chain launch), Koi reads (waiting/running jobs + active chains)
- `PlanStore` — the Koi → Orca handoff: Koi `create`s a plan, Orca polls `unapplied` and `mark_applied`s (CAS)
- `ResourceMap` — wire contract only; the live map is an in-memory variable in Orca (single writer, versioned snapshots), not a table
- `CredentialStore` + `/credentials/<ref>` FastAPI app behind a worker bearer token

**`tandemn_user_data`**
- `PayloadRef` / `OutputRef` / `NormalizedRecord` core types
- Connector protocols + registry; `S3Connector` (JSONL, OpenAI batch-style inputs)
- `WorkerClient` (worker-side fetch/write), `HttpCredentialResolver` (resolve scoped creds at fetch time)
- `index_source` (Orca-side: input_source JSONB → PayloadRefs)

The `tandemn_user_data → tandemn_system_data` import direction is forbidden
by `.importlinter` and checked on every PR; workers run on customer GPU
nodes and must never reach canonical state.

**Next:** strangler-fig integration into `tandemn-system` (Orca) — `submit_batch`
cutover, chunk queue behind Orca's HTTP API, real STS/KMS/Vault behind the
credential issuer.

---

## Quick start

Requires Python 3.12, [uv](https://github.com/astral-sh/uv), and Docker.

```bash
# 1. Bring up Postgres + MinIO
make up

# 2. Install deps into a local .venv
make install

# 3. Run unit tests (no infra needed)
make test

# 4. Run integration tests (requires `make up`)
make test-integration
```

Tear down with `make down`. Wipe local data with `make down && docker volume rm tandemn-store_postgres-data tandemn-store_minio-data`.

---

## Local services

Ports are non-default to avoid clashing with developer-local installs.

| Service  | Host URL                             | Container port | Credentials                          |
|----------|--------------------------------------|----------------|--------------------------------------|
| Postgres | `localhost:55432`                    | 5432           | `tandemn` / `tandemn` / db `tandemn` |
| MinIO    | `localhost:59000` (API), `:59001` (console) | 9000 / 9001 | `tandemn` / `tandemn-dev-key`        |

MinIO exists only as the S3-compatible test double; production targets
real S3. CI must never require AWS.

Override via env vars: `TANDEMN_POSTGRES_URL`.

---

## Layout

```
src/
├── tandemn_system_data/         # canonical state (Orca + Koi)
│   ├── models/                  # Pydantic models
│   ├── db/                      # SQLAlchemy ORM
│   ├── migrations/              # Alembic
│   ├── clients/                 # Postgres / event log / credentials / S3
│   ├── ids.py                   # canonical ID generator
│   └── events.py                # event envelope + payload registry
└── tandemn_user_data/           # user payloads (Orca + workers + CLI)
    ├── core/                    # refs, records, protocols, resolver
    ├── connectors/              # s3 (one PR per new source)
    ├── worker/                  # WorkerClient
    └── orca/                    # source indexer
```

For a visual of the canonical schema (tables, foreign keys, key columns)
see [`DATABASE.md`](./DATABASE.md).
