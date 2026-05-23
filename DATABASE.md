# Database

Visual reference for the canonical Postgres spine implemented by
`tandemn_system_data`. Mirrors `DATA_ARCHITECTURE.md` §5.

This file is the no-install path; for live exploration of data, use
DBeaver (see [Live exploration](#live-exploration) below).

---

## Entity-relationship diagram

Tables, primary keys, foreign keys, and the columns that carry meaning
beyond timestamps and statuses. JSONB columns are flagged with `(jsonb)`.

```mermaid
erDiagram
    tenants ||--o{ jobs            : "owns"
    tenants ||--o{ resource_maps   : "snapshots"
    tenants ||--o{ credentials     : "owns"

    jobs ||--o{ decisions          : "produces"

    plans ||--o{ decisions               : "referenced by (RESTRICT)"
    plans ||--o{ placement_alternatives  : "contains"

    placement_alternatives ||--o{ chains : "launches"

    chains ||--o{ attempts  : "has"
    chains ||--o{ outcomes  : "produces"

    tenants {
      TEXT tenant_id PK
      TEXT name
      TIMESTAMPTZ created_at
    }

    resource_maps {
      TEXT resource_map_id PK
      TEXT tenant_id FK
      JSONB snapshot_json
      TIMESTAMPTZ captured_at
    }

    jobs {
      TEXT job_id PK
      TEXT tenant_id FK
      VARCHAR kind
      JSONB spec_json
      JSONB input_source
      JSONB output_target
      VARCHAR status
      TIMESTAMPTZ created_at
      TIMESTAMPTZ completed_at "nullable"
    }

    plans {
      TEXT plan_id PK
      JSONB plan_json
      JSONB slo_json
      TIMESTAMPTZ created_at
    }

    decisions {
      TEXT decision_id PK
      TEXT job_id FK
      TEXT plan_id FK
      VARCHAR koi_version "nullable"
      JSONB rationale_json
      TIMESTAMPTZ created_at
    }

    placement_alternatives {
      TEXT alternative_id PK
      TEXT plan_id FK
      INT rank
      VARCHAR strategy "pd_disaggregated | aggregate"
      NUMERIC pd_ratio "NULL for aggregate"
      JSONB sizing_json
      NUMERIC estimated_throughput_tps "nullable"
      VARCHAR status
      TIMESTAMPTZ created_at
    }

    chains {
      TEXT chain_id PK
      TEXT alternative_id FK
      VARCHAR role "prefill | decode | aggregate"
      JSONB shape_json
      JSONB parallelism_json
      TEXT target_node "nullable"
      VARCHAR status
      TIMESTAMPTZ created_at
    }

    attempts {
      TEXT attempt_id PK
      TEXT chain_id FK
      VARCHAR status
      TIMESTAMPTZ started_at
      TIMESTAMPTZ ended_at "nullable"
      VARCHAR reason_code "nullable"
    }

    outcomes {
      TEXT outcome_id PK
      TEXT chain_id FK
      VARCHAR status
      VARCHAR reason_code "nullable"
      JSONB metrics_json
      TIMESTAMPTZ created_at
    }

    events {
      TEXT event_id PK
      TEXT tenant_id "nullable, no FK"
      TEXT job_id    "nullable, no FK"
      TEXT chain_id  "nullable, no FK"
      VARCHAR type
      JSONB payload_json
      TIMESTAMPTZ created_at
    }

    credentials {
      TEXT credentials_ref PK
      TEXT tenant_id FK
      JSONB scope_json
      BYTEA secret_payload "UTF-8 JSON; encrypted at rest in prod"
      TIMESTAMPTZ expires_at
      TEXT rotated_from "nullable, prior credentials_ref"
      TIMESTAMPTZ created_at
    }
```

---

## Foreign-key map

The same graph in text, useful for grep and for non-Mermaid renderers.

```
tenants(tenant_id)               ← resource_maps.tenant_id           CASCADE
tenants(tenant_id)               ← jobs.tenant_id                    CASCADE
tenants(tenant_id)               ← credentials.tenant_id             CASCADE

jobs(job_id)                     ← decisions.job_id                  CASCADE
plans(plan_id)                   ← decisions.plan_id                 RESTRICT
plans(plan_id)                   ← placement_alternatives.plan_id    CASCADE

placement_alternatives(alt_id)   ← chains.alternative_id             CASCADE
chains(chain_id)                 ← attempts.chain_id                 CASCADE
chains(chain_id)                 ← outcomes.chain_id                 CASCADE
```

`events` deliberately has **no** foreign keys to `jobs` / `chains` /
`tenants` — the audit log must survive cascade deletes of upstream rows.
This is the §8 "CP record alongside AP delivery" pattern.

---

## Read it in one sentence

> A **tenant** submits **jobs**; Koi produces a **decision** for each job
> that points at a **plan**; a plan carries ordered **placement
> alternatives** (with `pd_ratio` for PD-disaggregated, NULL for
> aggregate); each alternative launches **chains** (with role
> prefill / decode / aggregate); each chain has **attempts** and produces
> **outcomes**; every state change emits an **event** into the durable
> audit log; **credentials** are short-lived, scoped secrets the worker
> resolves at fetch time.

---

## Indexes worth knowing

Defined in `tandemn_system_data/db/orm.py`:

- `resource_maps`: GIN(`snapshot_json` jsonb_path_ops) for hierarchical inventory queries; (tenant_id, captured_at)
- `jobs`: (tenant_id, created_at); (status)
- `decisions`: (job_id); (plan_id)
- `placement_alternatives`: (plan_id, rank) — the natural order for fallback traversal
- `chains`: (alternative_id, role); (status)
- `attempts`: (chain_id)
- `outcomes`: (chain_id)
- `events`: (job_id, created_at); (chain_id, created_at); (tenant_id, created_at); (type, created_at) — supports the "show me everything about job_xyz" query in DATA_ARCHITECTURE.md §12
- `credentials`: (tenant_id); (expires_at)

---

## Live exploration

For data browsing, query history, and an interactive ERD, install DBeaver
and connect to the docker-compose Postgres:

```bash
brew install --cask dbeaver-community   # macOS
# Linux/Windows: https://dbeaver.io/download/
```

Then create a new PostgreSQL connection:

| Field    | Value     |
|----------|-----------|
| Host     | localhost |
| Port     | 55432     |
| Database | tandemn   |
| User     | tandemn   |
| Password | tandemn   |

Once connected, right-click the `public` schema → **View Diagram** for
the auto-generated ERD with the same shape as the Mermaid diagram above,
but interactive (drag/zoom/export PNG/SVG).

To browse the schema from the command line instead:

```bash
make migrate            # ensure the latest schema is applied
docker exec -it tandemn-postgres psql -U tandemn -d tandemn -c "\dt"
docker exec -it tandemn-postgres psql -U tandemn -d tandemn -c "\d+ chains"
```
