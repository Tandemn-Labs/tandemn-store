# AGENTS.md

This file is for coding agents. It is laid out as organization wide rules followed by repo-specific information.

Current repo: tandemn-labs/tandemn-store

## Organization guide

### Overall coding style
- Avoid clever one-liners that hurt readability.
- Use comments only for non-obvious operational logic, failure modes, or cross-service contracts. Do not comment what the code already says.
- Follow the existing local patterns before inventing a new one.
- Simplicity first. No features beyond what was asked. No abstractions for single-use code. No "flexibility" or "configurability" that wasn't requested. No error handling for impossible scenarios. Do not add unnecessary complexity in order to attain goals like scalability and security.
- Make only surgical changes. Touch only what is needed, don't improve or refractor anything that is not absolutely necessary.
- Work backwards; Define the GOAL first (success criteria) then ASK QUESTIONS till verified. Your goal is to transform the goal into sub-tasks and verifiable goals. For multi-step taks, state a brief plan.

### Python rules
- Use PEP 8 as code style guide and PEP 257 as docstrings style guide.
- Ensure `pyproject.toml` exists with `ruff`, `mypy` rules
- Use the `./src/` layout for code
- Use `uv` for virtual environment
- Use the python stdlib `logging` library instead of `print()` in the codebase

### Testing Philosophy
- Integration tests should use local containers; never real cloud accounts.

### Repository Boundaries
- Do not commit credentials, .env files, generated caches, local Docker volumes, or large artifacts.

### YAML rules
- Use `.yaml` for new files.

### Other rules
- Ensure `.pre-commit-config.yaml` exists


## Repo-specific guide

`tandemn-store` is the canonical data layer for Tandemn (Orca + Koi + workers), not an application server. It defines shared data contracts consumed by multiple repos.

### Project identity

- Two packages with different responsibilities:
  - `tandemn_system_data`: control-plane state for Orca and Koi (Postgres spine, Alembic, Postgres event log, internal blobs, credentials store/server, JobStore, resource map contract).
  - `tandemn_user_data`: data-plane payload movement for Orca, workers, and CLI (PayloadRef, OutputRef, NormalizedRecord, connectors, worker fetch/write path).
- Keep the package boundary strict: `tandemn_user_data` must never import `tandemn_system_data`. CI enforces this with `import-linter`.
- The source-of-truth architecture is in `DATA_ARCHITECTURE.md` at the repo root; update it when changing the contract.

### Schema and migration rules

- Pydantic models, SQLAlchemy ORM, Alembic migrations, `DATABASE.md`, and `DATA_ARCHITECTURE.md` must stay in sync.
- Any ORM schema change requires an Alembic migration and an `alembic check` pass.
- The canonical spine is exactly: `users`, `jobs`, `plans`, `chains`, `events`(+offsets), `credentials`. Chains are job-scoped. Job statuses are exactly `waiting | running | paused | finished` (`finish_reason` NULL = success). Koi ticks, attempts, and outcomes are events, not tables; do not re-add `koi_ticks`, `ranks`, `plan_jobs`, `attempts`, or `outcomes`.
- The resource map is NOT a Postgres table. It is Orca's in-memory state; this repo ships only the `ResourceMap` wire contract. Do not re-add a `resource_maps` table.
- `plans` are one Koi pass's decision: `tick_rationale` plus `actions_json` (per-job `place|keep|defer|preempt|swap`, ladders with expected TPS inside). No throughput columns in the database; no traversal in the MVP (placements gang-launch their chains). Do not reintroduce a separate `decisions` table unless explicitly requested.
- Use Postgres JSONB for schemaless-but-attached state (`actions_json`, `spec_json`, `shape_json`, `input_source`, `output_target`). Do not add Mongo/Dynamo just for hierarchical blobs.

### Control plane / data plane boundary

- User data bytes must not transit Orca or Postgres. Orca handles metadata and pointers only.
- Future chunk queues carry metadata (`payload_ref`, `output_ref`, `chain_id`) and leases/retries, not prompt bytes.
- `S3BlobClient` is for Tandemn-owned internal blobs only. User data sources go through `tandemn_user_data.connectors`.
- Workers use `tandemn_user_data` only. They fetch bytes directly from user data systems and resolve scoped credentials at fetch time.
- Avoid connector sprawl. Add a new connector only when needed; keep provider-specific code isolated under `tandemn_user_data/connectors/`.

### Linting, formatting, and tests

- Use repo tooling, not ad hoc choices: `uv`, `ruff`, `mypy`, `pytest`, `alembic`, `import-linter`, `pre-commit`.
- Run before submitting library changes:
  - `uv run ruff check src tests`
  - `uv run ruff format --check src tests`
  - `uv run mypy`
  - `uv run pytest -m "not integration"`
  - `uv run lint-imports`
- If Docker is available and behavior or migrations changed, also run `uv run pytest -m integration` and `uv run alembic check`.
- If Docker is not running, say so explicitly and rely on GitHub Actions for integration verification.
- Protect the contract, not just implementation details: schema relationships, event payloads, credential expiry, import boundaries, connector semantics, and migration drift. For bug fixes, add focused regression tests.

### CI/CD expectations

- GitHub Actions is the source of truth for PR/push checks.
- CI runs lint, format check, import-linter, unit tests, Postgres/MinIO integration tests, and `alembic check`.
- Do not add CI steps that require AWS, GPUs, paid cloud resources, gated model downloads, or external secrets. Use MinIO for S3-compatible tests.

### Dependency policy

- Keep dependencies narrow and stable. This is a shared library consumed by multiple repos.
- Be especially careful when bumping SQLAlchemy, Alembic, Pydantic, FastAPI, httpx, boto3/botocore, or uvicorn; call out operational impact and test coverage.
- Do not add heavyweight cloud/data dependencies to the base package for future connectors. Prefer optional extras or delayed connector-specific dependencies.

### Repository boundaries

- This repo should not import Orca or Koi internals.
- Orca integration belongs in `tandemn-system`; Koi integration belongs in `tandemn-intelligence`.

### Editing agent instruction files

- Keep `AGENTS.md` under 200 lines.
- Add rules only when an agent would likely do the wrong thing without them.
- Do not copy tool documentation here; rely on repo config and existing scripts.
