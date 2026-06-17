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
    users ||--o{ plans           : "schedules"
    users ||--o{ credentials     : "owns"
    users ||--o| resource_maps   : "capacity snapshot"
    users ||--o{ evidence_rows   : "Koi learning"
    users ||--o{ koi_causal_nodes : "Koi topology"
    users ||--o{ koi_causal_edges : "Koi topology"
    users ||--o{ koi_causal_mechanisms : "Koi topology"

    jobs ||--o{ chains           : "served by"
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
      VARCHAR status "waiting | running | paused | finished"
      VARCHAR finish_reason "NULL = success"
      TIMESTAMPTZ created_at
      TIMESTAMPTZ finished_at "nullable"
    }

    plans {
      TEXT plan_id PK
      TEXT user_id FK
      VARCHAR koi_version "nullable"
      TEXT tick_rationale
      JSONB actions_json "per-job place/keep/defer/preempt/swap"
      VARCHAR status "created | applied"
      TIMESTAMPTZ created_at
    }

    chains {
      TEXT chain_id PK
      TEXT job_id FK
      TEXT plan_id "provenance, no FK"
      VARCHAR role "prefill | decode | aggregate"
      JSONB shape_json "gpu, count, tp, pp"
      TEXT target_node "nullable"
      VARCHAR status "launching | running | stopped | failed"
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

    resource_maps {
      TEXT user_id PK FK
      INT version "monotonic per replace"
      JSONB pools_json "capacity_type + clouds tree"
      TIMESTAMPTZ updated_at
    }

    evidence_rows {
      TEXT row_id PK
      TEXT user_id FK
      INT tick
      TEXT job_id
      TEXT rank_id
      FLOAT deploy_timestamp_utc
      JSONB payload_json
      TIMESTAMPTZ created_at
    }

    koi_causal_nodes {
      TEXT user_id PK FK
      TEXT node_id PK
      VARCHAR node_type "X | V | Y"
      TEXT description "nullable"
      TEXT unit "nullable"
    }

    koi_causal_edges {
      TEXT user_id PK FK
      TEXT edge_id PK
      TEXT src
      TEXT dst
      VARCHAR src_type
      VARCHAR dst_type
      VARCHAR status
      FLOAT alpha
      FLOAT beta
      INT visit_count
      INT last_touched_tick "nullable"
      JSONB q_histogram_json
      JSONB envs_seen_json
      FLOAT q3_frequency
    }

    koi_causal_mechanisms {
      TEXT user_id PK FK
      TEXT mechanism_id PK
      TEXT name
      JSONB edge_ids_json
      JSONB scope_json
      TEXT narrative
      VARCHAR status
      TEXT archived_reason "nullable"
      FLOAT alpha
      FLOAT beta
      INT visit_count
      INT last_touched_tick "nullable"
      JSONB q_histogram_json
      JSONB envs_seen_json
      INT inspection_count
    }
```

Not tables, on purpose:

- **koi ticks** — `tick.started` / `tick.completed` events; `tick_id` is a
  correlation string. FSM `tick` integers index `evidence_rows.tick`.

**`resource_maps.pools_json`** holds `{capacity_type, clouds}` — the same
hierarchical shape as `ResourceMap` (`clouds → regions → zones →
network_fabrics → machine_pools`). Row columns `version` and `updated_at`
mirror the wire contract. Orca `replace`s; Koi `get`s and calls
`scheduling_summary()` for flat GPU counts.

**`evidence_rows`** (Koi learning / replay — not Orca handoff): indexed
columns in the diagram; heavy fields in `payload_json`. Query path:
`EvidenceStore.recent(user_id, last_n_ticks=N)`.

**`koi_causal_*`** (Koi topology + Beta confidence — not Orca handoff):
three tables co-locate edge/mechanism metadata with topology. Koi loads at
boot via `CausalGraphStore`, mutates in memory during a tick, syncs back
with `sync_edge_metadata` / `sync_mechanisms` after S3 confidence updates.

- **ranks / ladders** — live inside `plans.actions_json`; `evidence_rows.rank_id`
  labels a ladder step in Koi only. No traversal in the MVP; Orca gang-launches
  what a placement describes.

---

## Foreign-key map

The same graph in text, useful for grep and for non-Mermaid renderers.

```
users(user_id)   ← jobs.user_id          CASCADE
users(user_id)   ← plans.user_id         CASCADE
users(user_id)   ← credentials.user_id   CASCADE
users(user_id)   ← resource_maps.user_id CASCADE
users(user_id)   ← evidence_rows.user_id CASCADE
users(user_id)   ← koi_causal_nodes.user_id CASCADE
users(user_id)   ← koi_causal_edges.user_id CASCADE
users(user_id)   ← koi_causal_mechanisms.user_id CASCADE

jobs(job_id)     ← chains.job_id         CASCADE
```

`chains.plan_id` is provenance only (no FK): plans and chains have
independent lifecycles.

`events` deliberately has **no** foreign keys to `jobs` / `chains` /
`users` — the audit log must survive cascade deletes of upstream rows.
Consumers track their own cursor in `event_consumer_offsets` and update it
only after successful processing.

---

## Read it in one sentence

> A **user** submits **jobs** (status `waiting`); each Koi pass produces a
> **plan** — a rationale plus per-job actions (`place`, `keep`, `defer`,
> `preempt`, `swap`); Orca applies the actions, gang-launching the
> **chains** a placement describes (prefill + decode together for PD);
> every state change emits an **event** into the durable audit log;
> **credentials** are short-lived, scoped secrets the worker resolves at
> fetch time.

---

## Indexes worth knowing

Defined in `tandemn_system_data/db/orm.py`:

- `jobs`: (user_id, created_at); (status)
- `plans`: (user_id, created_at); (status)
- `chains`: (job_id); (status)
- `events`: (job_id, created_at); (chain_id, created_at); (user_id, created_at); (type, created_at) — supports the "show me everything about job_xyz" query in DATA_ARCHITECTURE.md §12
- `event_consumer_offsets`: primary key on `consumer_name`
- `credentials`: (user_id); (expires_at)
- `evidence_rows`: (user_id, tick); (user_id, job_id, tick)
- `koi_causal_nodes`, `koi_causal_edges`, `koi_causal_mechanisms`: composite PK `(user_id, …)`

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
