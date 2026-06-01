# tandemn-store

Canonical data layer for Tandemn (Orca + Koi + workers).

Ships two packages:

- **`tandemn_system_data`** — canonical state (Postgres spine, Postgres event log, Tandemn-owned S3 blobs). Imported by **Orca and Koi only**.
- **`tandemn_user_data`** — user payloads in motion (connectors, credentials, `PayloadRef` / `OutputRef`). Imported by **Orca, workers, and CLI**.

The architecture and rationale live in `tandemn-system/DATA_ARCHITECTURE.md`.

---

## Status

**Phase 1a (done):** scaffold + connectivity. Both packages import. Postgres, Redis, and MinIO start via `make up`. Smoke tests pass.

**Phase 1b (done):** canonical IDs, Pydantic models, typed event payload registry, SQLAlchemy ORM mirroring DATA_ARCHITECTURE.md §5, Alembic baseline migration, and an end-to-end roundtrip test that goes through the migration.

**Phase 1c (done):** `tandemn_user_data` core types (`PayloadRef`, `OutputRef`, `NormalizedRecord`), connector protocols + registry, `LocalFileConnector` (JSONL on disk), `S3Connector` (JSONL on S3/MinIO), worker-side `WorkerClient` / `fetch_payload` / `write_outputs`, Orca-side `index_source` and `DevCredentialIssuer`, and an end-to-end test of the full §7 dataflow.

**Phase 1d (done):** `CredentialStore` (canonical persistence), `/credentials/<ref>` FastAPI app behind a worker-bearer-token header, `HttpCredentialResolver` (worker-side, no system_data imports), full §7 lifecycle e2e through real HTTP, `import-linter` enforcing the §1 principle 2 boundary, GitHub Actions CI running lint + unit + import-linter + integration + `alembic check` on every PR.

**Phase 1e (done):** `PostgresEventLog` implements the MVP event path in §8: append event rows, read by cursor, maintain `event_consumer_offsets`, and let Koi/Orca poll events durably without Redis Streams.

**Phase 1f (done):** Redis-backed chunk queue implements the hot batch work queue: Orca/admin creates queues and reclaims expired chunks; workers pull, renew, complete, and fail chunks using `payload_ref`, `output_ref`, and `chain_id` metadata.

**Phase 2 (next):** Strangler-fig integration into `tandemn-system` (Orca) — `USE_CANONICAL_STORE` feature flag, `submit_batch` cutover, real STS / KMS / Vault behind `CredentialIssuer`, replace the rest of the webhook flows with Postgres events.

---

## Quick start

Requires Python 3.12, [uv](https://github.com/astral-sh/uv), and Docker.

```bash
# 1. Bring up Postgres + Redis + MinIO
make up

# 2. Install deps into a local .venv
make install

# 3. Run unit tests (no infra needed)
make test

# 4. Run integration smoke (requires `make up`)
make test-integration
```

Tear down with `make down`. Wipe local data with `make down && docker volume rm tandemn-store_postgres-data tandemn-store_redis-data tandemn-store_minio-data`.

---

## Local services

Ports are non-default to avoid clashing with developer-local installs.

| Service  | Host URL                             | Container port | Credentials                          |
|----------|--------------------------------------|----------------|--------------------------------------|
| Postgres | `localhost:55432`                    | 5432           | `tandemn` / `tandemn` / db `tandemn` |
| Redis    | `localhost:56379`                    | 6379           | none                                 |
| MinIO    | `localhost:59000` (API), `:59001` (console) | 9000 / 9001 | `tandemn` / `tandemn-dev-key`        |

Override via env vars: `TANDEMN_POSTGRES_URL`, `TANDEMN_REDIS_URL`, `TANDEMN_S3_ENDPOINT`, `TANDEMN_S3_ACCESS_KEY`, `TANDEMN_S3_SECRET_KEY`, `TANDEMN_S3_BUCKET`.

---

## Layout

```
src/
├── tandemn_system_data/         # canonical state (Orca + Koi)
│   ├── models/                  # Pydantic models           (Phase 1b ✅)
│   ├── db/                      # SQLAlchemy ORM            (Phase 1b ✅)
│   ├── migrations/              # Alembic                   (Phase 1b ✅)
│   ├── clients/                 # Postgres / events / chunk admin / S3
│   │                            # (Phase 1a/e/f ✅)
│   ├── ids.py                   # canonical ID generator    (Phase 1b ✅)
│   └── events.py                # Event envelope            (Phase 1b ✅)
└── tandemn_user_data/           # user payloads (Orca + workers + CLI)
    ├── core/                    # NormalizedRecord, refs +
    │                            # HttpCredentialResolver    (Phase 1c/d ✅)
    ├── connectors/              # S3 / local / future       (Phase 1c ✅)
    ├── worker/                  # WorkerClient + chunk worker queue
    │                            # (Phase 1c/f ✅)
    └── orca/                    # indexer / dev issuer      (Phase 1c ✅)
```

For a visual of the canonical schema (tables, foreign keys, key
columns) see [`DATABASE.md`](./DATABASE.md). The diagram renders inline
on GitHub.

The `tandemn_user_data → tandemn_system_data` direction is forbidden by
`.importlinter` and checked on every PR. Workers must never import
`tandemn_system_data`. See `DATA_ARCHITECTURE.md` §1 principle 2 for why.
