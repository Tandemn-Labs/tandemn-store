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
    users ||--o{ jobs            : "owns"
    users ||--o{ credentials     : "owns"
    users ||--o{ plans           : "schedules"

    plans ||--o{ plan_jobs       : "includes"
    jobs ||--o{ plan_jobs        : "admitted"

    plans ||--o{ ranks  : "contains"

    ranks ||--o{ chains : "launches"

    chains ||--o{ attempts  : "has"
    chains ||--o{ outcomes  : "produces"
    event_consumer_offsets ||--o{ events : "cursor into"

    users {
      TEXT user_id PK
      TEXT name
      TIMESTAMPTZ created_at
    }

    jobs {
      TEXT job_id PK
      TEXT user_id FK
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
      TEXT user_id FK
      VARCHAR koi_version "nullable"
      JSONB rationale_json
      JSONB plan_json
      JSONB slo_json
      NUMERIC required_throughput_tps "nullable"
      VARCHAR status
      TIMESTAMPTZ created_at
    }

    plan_jobs {
      TEXT plan_id PK, FK
      TEXT job_id PK, FK
      INT priority
      NUMERIC required_throughput_tps "nullable"
      VARCHAR status
      TIMESTAMPTZ admitted_at
    }

    ranks {
      TEXT rank_id PK
      TEXT plan_id FK
      INT rank_index
      VARCHAR strategy "pd_disaggregated | aggregate"
      NUMERIC pd_ratio "NULL for aggregate"
      JSONB sizing_json
      NUMERIC estimated_throughput_tps "nullable"
      NUMERIC realized_throughput_tps "nullable"
      VARCHAR status
      TIMESTAMPTZ created_at
    }

    chains {
      TEXT chain_id PK
      TEXT rank_id FK
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
      TEXT user_id "nullable, no FK"
      TEXT job_id    "nullable, no FK"
      TEXT chain_id  "nullable, no FK"
      VARCHAR type
      JSONB payload_json
      TIMESTAMPTZ created_at
    }

    event_consumer_offsets {
      TEXT consumer_name PK
      TEXT last_event_id "nullable"
      TIMESTAMPTZ updated_at
    }

    credentials {
      TEXT credentials_ref PK
      TEXT user_id FK
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
users(user_id)               ← jobs.user_id                    CASCADE
users(user_id)                   ← credentials.user_id             CASCADE
users(user_id)                   ← plans.user_id                   CASCADE

plans(plan_id)                   ← plan_jobs.plan_id               CASCADE
jobs(job_id)                     ← plan_jobs.job_id                CASCADE
plans(plan_id)                   ← ranks.plan_id                   CASCADE

ranks(rank_id)   ← chains.rank_id             CASCADE
chains(chain_id)                 ← attempts.chain_id                 CASCADE
chains(chain_id)                 ← outcomes.chain_id                 CASCADE
```

`events` deliberately has **no** foreign keys to `jobs` / `chains` /
`users` — the audit log must survive cascade deletes of upstream rows.
Consumers track their own cursor in `event_consumer_offsets` and update it
only after successful processing.

---

## Read it in one sentence

> A **user** submits **jobs**; each Koi tick considers waiting/running
> jobs and produces a multi-job **plan**. The plan carries both Koi's
> rationale and the executable placement plan. That plan contains ordered
> **ranks** (with
> `pd_ratio` for PD-disaggregated, NULL for
> aggregate); each rank launches **chains** (with role
> prefill / decode / aggregate); each chain has **attempts** and produces
> **outcomes**; every state change emits an **event** into the durable
> audit log; **credentials** are short-lived, scoped secrets the worker
> resolves at fetch time.

---

## Indexes worth knowing

Defined in `tandemn_system_data/db/orm.py`:

- `jobs`: (user_id, created_at); (status)
- `plans`: (user_id, created_at); (status)
- `plan_jobs`: (job_id); (status)
- `ranks`: (plan_id, rank_index) — the natural order for deployment traversal
- `chains`: (rank_id, role); (status)
- `attempts`: (chain_id)
- `outcomes`: (chain_id)
- `events`: (job_id, created_at); (chain_id, created_at); (user_id, created_at); (type, created_at) — supports the "show me everything about job_xyz" query in DATA_ARCHITECTURE.md §12
- `event_consumer_offsets`: primary key on `consumer_name`
- `credentials`: (user_id); (expires_at)

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
