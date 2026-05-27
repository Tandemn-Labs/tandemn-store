# Agent Instructions for Tandemn Store

This file is for coding agents working in `tandemn-store`. Keep it lean: this repo defines shared data contracts used by Orca, Koi, workers, and eventually the CLI.

## Project Identity

- `tandemn-store` is the canonical data layer for Tandemn, not an application server.
- It ships two packages with different responsibilities:
  - `tandemn_system_data`: control-plane state for Orca and Koi (Postgres spine, Alembic, events, Redis Streams, internal blobs, credentials store/server).
  - `tandemn_user_data`: data-plane payload movement for Orca, workers, and CLI (PayloadRef, OutputRef, NormalizedRecord, connectors, worker fetch/write path).
- Keep the package boundary strict: `tandemn_user_data` must never import `tandemn_system_data`. CI enforces this with `import-linter`.
- The source-of-truth architecture is in `../tandemn-system/DATA_ARCHITECTURE.md`; update it when changing the contract.

## Code Style

- Prefer small, direct modules over broad frameworks. Explicit control flow beats clever generalization.
- Keep contracts boring and legible for systems engineers operating production infrastructure.
- Use comments only for non-obvious operational behavior, cross-service contracts, failure modes, or security boundaries.
- Avoid connector sprawl. Add a new connector only when needed; keep provider-specific code isolated under `tandemn_user_data/connectors/`.

## Schema and Migration Rules

- Pydantic models, SQLAlchemy ORM, Alembic migrations, `DATABASE.md`, and `DATA_ARCHITECTURE.md` must stay in sync.
- Any ORM schema change requires an Alembic migration and an `alembic check` pass.
- The current canonical hierarchy is: `user -> job -> plan -> placement_alternative -> chain -> attempt/outcome/event`.
- `plans` are the collapsed Koi object: they contain both rationale (`rationale_json`, `koi_version`) and executable placement (`plan_json`, `slo_json`). Do not reintroduce a separate `decisions` table unless explicitly requested.
- Use Postgres JSONB for schemaless-but-attached state (`plan_json`, `sizing_json`, `metrics_json`, `input_source`, `output_target`). Do not add Mongo/Dynamo just for hierarchical blobs.

## Control Plane / Data Plane Boundary

- User data bytes must not transit Orca, Postgres, or Redis Streams. Orca handles metadata and pointers only.
- Redis chunk queues carry metadata (`payload_ref`, `output_ref`, `chain_id`) and leases/retries, not prompt bytes.
- `S3BlobClient` is for Tandemn-owned internal blobs only. User data sources go through `tandemn_user_data.connectors`.
- Workers use `tandemn_user_data` only. They fetch bytes directly from user data systems and resolve scoped credentials at fetch time.

## Linting, Formatting, and Tests

- Use repo tooling, not ad hoc choices: `uv`, `ruff`, `pytest`, `alembic`, `import-linter`.
- Run before submitting library changes:
  - `uv run ruff check src tests`
  - `uv run ruff format --check src tests`
  - `uv run pytest -m "not integration"`
  - `uv run lint-imports`
- If Docker is available and behavior or migrations changed, also run `uv run pytest -m integration` and `uv run alembic check`.
- If Docker is not running, say so explicitly and rely on GitHub Actions for integration verification.

## CI/CD Expectations

- GitHub Actions is the source of truth for PR/push checks.
- CI runs lint, format check, import-linter, unit tests, Postgres/Redis/MinIO integration tests, and `alembic check`.
- Do not add CI steps that require AWS, GPUs, paid cloud resources, gated model downloads, or external secrets. Use MinIO for S3-compatible tests.

## Dependency Policy

- Keep dependencies narrow and stable. This is a shared library consumed by multiple repos.
- Be especially careful when bumping SQLAlchemy, Alembic, Pydantic, Redis, FastAPI, httpx, boto3/botocore, or uvicorn; call out operational impact and test coverage.
- Do not add heavyweight cloud/data dependencies to the base package for future connectors. Prefer optional extras or delayed connector-specific dependencies.

## Testing Philosophy

- Protect the contract, not just implementation details: schema relationships, event payloads, credential expiry, import boundaries, connector semantics, and migration drift.
- For bug fixes, add focused regression tests.
- Integration tests should use local containers (Postgres, Redis, MinIO), never real cloud accounts.

## Repository Boundaries

- This repo should not import Orca or Koi internals.
- Orca integration belongs in `tandemn-system`; Koi integration belongs in `tandemn-intelligence`.
- Do not commit credentials, `.env` files, generated caches, local Docker volumes, or large artifacts.

## Editing Agent Instruction Files

- Keep `AGENTS.md` under 200 lines.
- Add rules only when an agent would likely do the wrong thing without them.
- Do not copy tool documentation here; rely on repo config and existing scripts.
