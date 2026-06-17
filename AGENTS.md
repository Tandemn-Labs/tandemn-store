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

`tandemn-store` is the canonical data layer for Tandemn (Orca + Koi + workers), not an application server.

- **`tandemn_system_data`**: control-plane state (Postgres spine, Alembic, event log, credentials, JobStore, PlanStore, resource map contract, Koi `EvidenceRow` wire type).
- **`tandemn_user_data`**: data-plane payloads (connectors, PayloadRef/OutputRef, worker fetch path). Must never import `tandemn_system_data` (enforced by import-linter).
- **`DATA_ARCHITECTURE.md`** is the contract source of truth; keep it, Pydantic models, ORM, and Alembic migrations in sync.

**Schema invariants:** spine is `users`, `jobs`, `plans`, `chains`, `events`(+offsets), `credentials`, `resource_maps`, plus Koi-only `evidence_rows` and `koi_causal_*` (nodes, edges+metadata, mechanisms+metadata). Job statuses: `waiting | running | paused | finished`. Plans are `tick_rationale` + `actions_json`. Chains are job-scoped. One `resource_maps` row per user; `pools_json` is hierarchical (`clouds → regions → zones → network_fabrics → machine_pools`). Do not re-add `koi_ticks`, `ranks`, `plan_jobs`, `attempts`, or `outcomes`. No throughput columns; MVP gang-launches chains (no traversal).

**Boundaries:** user data bytes do not transit Orca or Postgres. No Tandemn-owned blob client in MVP. Workers use `tandemn_user_data` only. Orca/Koi integration belongs in `tandemn-system` / `tandemn-intelligence`, not here.

**Changes:** ORM edits require an Alembic migration and `alembic check`. Shared library — keep dependencies narrow.
