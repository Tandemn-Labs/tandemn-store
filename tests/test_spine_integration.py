"""Integration: the canonical spine — migrations, hierarchy round-trip,
JobStore, event log. Requires Postgres (`make up`)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from tandemn_system_data.clients import (
    CausalGraphStore,
    EvidenceStore,
    GpuMetricStore,
    JobStore,
    ModelCatalogStore,
    PlanStore,
    PostgresClient,
    PostgresEventLog,
    ResourceMapStore,
    UserStore,
)
from tandemn_system_data.clients.causal_graph_store import edge_to_row, node_to_row
from tandemn_system_data.db import ALL_TABLES, EventRow, JobRow, PlanRow, RankRow, UserRow
from tandemn_system_data.ids import (
    new_event_id,
    new_job_id,
    new_plan_id,
    new_rank_id,
    new_user_id,
)
from tandemn_system_data.models import (
    ActionType,
    CausalEdge,
    CausalMechanism,
    CausalNode,
    EdgeMetadata,
    Event,
    EvidenceRow,
    GpuMetric,
    Job,
    JobKind,
    JobStatus,
    MechanismMetadata,
    ModelCatalog,
    Plan,
    PlanAction,
    Rank,
    RankRole,
    RankStatus,
    User,
    format_evidence_row_id,
)
from tandemn_system_data.models.resource_map import (
    Cloud,
    MachinePool,
    NetworkFabric,
    Region,
    ResourceMap,
    Zone,
)
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def _schema(fresh_schema):
    pass


@pytest.fixture
def store(pg_client: PostgresClient) -> JobStore:
    return JobStore(pg_client)


@pytest.fixture
def user_id(pg_client: PostgresClient) -> str:
    uid = new_user_id()
    with pg_client.begin() as s:
        s.add(UserRow(user_id=uid, name="spine-test", created_at=datetime.now(UTC)))
    return uid


# ----- Migrations ------------------------------------------------------------


def test_migration_creates_spine_and_matches_orm(pg_client: PostgresClient):
    db_tables = set(inspect(pg_client.engine).get_table_names())
    assert {row.__tablename__ for row in ALL_TABLES}.issubset(db_tables)

    result = subprocess.run(
        ["uv", "run", "alembic", "check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "No new upgrade operations detected" in (result.stdout + result.stderr)


# ----- Hierarchy round-trip ---------------------------------------------------


def test_full_hierarchy_roundtrip_and_cascades(pg_client: PostgresClient, user_id: str):
    """user -> job -> ranks + plan + event; ranks cascade with the job."""
    now = datetime.now(UTC)
    job_id, plan_id = new_job_id(), new_plan_id()
    prefill_id, decode_id, event_id = new_rank_id(), new_rank_id(), new_event_id()

    with pg_client.begin() as s:
        s.add(
            JobRow(
                job_id=job_id,
                user_id=user_id,
                kind="batch",
                spec_json={"model": "google/gemma-4-31B-it"},
                input_source={"type": "s3", "uri": "s3://ventura/inputs/x.jsonl"},
                output_target={"type": "s3", "uri": "s3://ventura/outputs/"},
                status="waiting",
                created_at=now,
            )
        )
        s.flush()
        s.add(
            PlanRow(
                plan_id=plan_id,
                user_id=user_id,
                tick_rationale="spare capacity; gang-place the PD pair",
                actions_json=[
                    {
                        "job_id": job_id,
                        "type": "place",
                        "ladder": [
                            {"prefill": {"gpu": "H100", "count": 8, "n_replicas": 2}},
                            {"decode": {"gpu": "A100", "count": 8, "n_replicas": 1}},
                        ],
                        "target_tps": 1500,
                    }
                ],
                status="applied",
                created_at=now,
            )
        )
        for rank_id, role, gpu, n_replicas in (
            (prefill_id, "prefill", "H100", 2),
            (decode_id, "decode", "A100", 1),
        ):
            s.add(
                RankRow(
                    rank_id=rank_id,
                    job_id=job_id,
                    plan_id=plan_id,
                    role=role,
                    shape_json={"gpu": gpu, "count": 8},
                    n_replicas=n_replicas,
                    status="running",
                    created_at=now,
                    updated_at=now,
                )
            )
        s.add(
            EventRow(
                event_id=event_id,
                user_id=user_id,
                job_id=job_id,
                rank_id=decode_id,
                type="rank.launched",
                payload_json={"rank_id": decode_id, "job_id": job_id, "role": "decode"},
                created_at=now,
            )
        )

    with pg_client.session() as s:
        plan = s.get(PlanRow, plan_id)
        assert plan.actions_json[0]["ladder"][0]["prefill"]["count"] == 8
        ranks = [s.get(RankRow, prefill_id), s.get(RankRow, decode_id)]
        assert {rank.role for rank in ranks} == {"prefill", "decode"}
        assert all(rank.job_id == job_id and rank.plan_id == plan_id for rank in ranks)

    with pg_client.begin() as s:
        s.delete(s.get(JobRow, job_id))

    with pg_client.session() as s:
        assert s.get(RankRow, prefill_id) is None  # cascaded
        assert s.get(EventRow, event_id) is not None  # audit log survives


# ----- JobStore ---------------------------------------------------------------


def test_job_lifecycle_with_cas(store: JobStore, user_id: str):
    """waiting -> running -> paused -> running -> finished, all CAS-guarded."""
    job = store.submit(Job(user_id=user_id, kind=JobKind.BATCH))
    assert store.get(job.job_id).status is JobStatus.WAITING

    assert store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.WAITING]) is True
    assert store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.WAITING]) is False  # CAS
    assert store.transition(job.job_id, JobStatus.PAUSED, [JobStatus.RUNNING]) is True
    assert store.paused_jobs(user_id)[-1].job_id == job.job_id
    assert store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.PAUSED]) is True

    assert store.transition(
        job.job_id, JobStatus.FINISHED, [JobStatus.RUNNING], finish_reason="FAILED"
    )
    done = store.get(job.job_id)
    assert done.finish_reason == "FAILED" and done.finished_at is not None

    assert store.transition("job_nope", JobStatus.RUNNING, [JobStatus.WAITING]) is False
    assert store.get("job_nope") is None


def test_job_failure_detail_and_retryable_error(store: JobStore, user_id: str):
    failed = store.submit(Job(user_id=user_id, kind=JobKind.ONLINE))
    assert store.fail(
        failed.job_id,
        [JobStatus.WAITING],
        finish_reason="MODEL_CATALOG_INVALID",
        error_message="max_num_seq missing for L40S",
    )
    failed = store.get(failed.job_id)
    assert failed.status is JobStatus.FINISHED
    assert failed.finish_reason == "MODEL_CATALOG_INVALID"
    assert failed.error_message == "max_num_seq missing for L40S"

    running = store.submit(Job(user_id=user_id, kind=JobKind.ONLINE))
    store.transition(running.job_id, JobStatus.RUNNING, [JobStatus.WAITING])
    assert store.set_error(running.job_id, "replacement catalog is incomplete")
    assert store.get(running.job_id).error_message == "replacement catalog is incomplete"
    assert store.set_error(running.job_id, None)
    assert store.get(running.job_id).error_message is None


def test_koi_reads_waiting_and_running_with_ranks(
    store: JobStore, pg_client: PostgresClient, user_id: str
):
    now = datetime.now(UTC)
    waiting = store.submit(Job(user_id=user_id, kind=JobKind.BATCH))
    running = store.submit(Job(user_id=user_id, kind=JobKind.BATCH))
    store.transition(running.job_id, JobStatus.RUNNING, [JobStatus.WAITING])

    live, dead = new_rank_id(), new_rank_id()
    with pg_client.begin() as s:
        for rank_id, status in ((live, "running"), (dead, "failed")):
            s.add(
                RankRow(
                    rank_id=rank_id,
                    job_id=running.job_id,
                    role="aggregate",
                    shape_json={"gpu": "H100", "count": 8},
                    n_replicas=1,
                    status=status,
                    created_at=now,
                    updated_at=now,
                )
            )

    assert waiting.job_id in {j.job_id for j in store.waiting_jobs(user_id)}
    assert waiting.job_id in {j.job_id for j in store.list_jobs(user_id)}
    mine = next(r for r in store.running_jobs(user_id) if r.job.job_id == running.job_id)
    assert [rank.rank_id for rank in mine.ranks] == [live]
    assert {rank.rank_id for rank in store.ranks(running.job_id)} == {live, dead}


def test_user_store_ensure_is_idempotent(pg_client: PostgresClient):
    user = User(user_id=new_user_id(), name="console-user")
    store = UserStore(pg_client)

    assert store.ensure(user) == user
    assert store.ensure(user) == user


# ----- PlanStore + rank helpers (the Koi -> Orca handoff) ---------------------


def test_plan_handoff_and_rank_launch(store: JobStore, pg_client: PostgresClient, user_id: str):
    """Koi writes a plan; Orca atomically launches its ranks."""
    plans = PlanStore(pg_client)
    job = store.submit(Job(user_id=user_id, kind=JobKind.BATCH))

    plan = plans.create(
        Plan(
            user_id=user_id,
            tick_rationale="capacity available; place the PD pair",
            actions=[
                PlanAction(
                    job_id=job.job_id,
                    type=ActionType.PLACE,
                    ladder=[
                        {"prefill": {"gpu": "H100", "count": 8, "n_replicas": 2}},
                        {"decode": {"gpu": "A100", "count": 8, "n_replicas": 1}},
                    ],
                    target_tps=1500,
                    target_p99_ttft_ms=500,
                    target_p99_tpot_ms=50,
                )
            ],
        )
    )

    # Orca's side: poll, apply, mark applied.
    pending = plans.unapplied(user_id)
    assert plan.plan_id in {p.plan_id for p in pending}
    assert plan.plan_id in {p.plan_id for p in plans.list_plans(user_id)}
    fetched = next(p for p in pending if p.plan_id == plan.plan_id)
    assert fetched.actions[0].type is ActionType.PLACE
    assert fetched.actions[0].target_p99_ttft_ms == 500
    assert fetched.actions[0].target_p99_tpot_ms == 50
    assert fetched.actions[0].ladder[0]["prefill"]["count"] == 8

    launched = store.launch_ranks(
        [
            Rank(
                job_id=job.job_id,
                plan_id=plan.plan_id,
                role=RankRole.PREFILL,
                shape_json={"gpu": "H100", "count": 8},
                n_replicas=2,
            ),
            Rank(
                job_id=job.job_id,
                plan_id=plan.plan_id,
                role=RankRole.DECODE,
                shape_json={"gpu": "A100", "count": 8},
                n_replicas=1,
            ),
        ]
    )
    store.transition(job.job_id, JobStatus.RUNNING, [JobStatus.WAITING])

    assert plans.mark_applied(plan.plan_id) is True
    assert plans.mark_applied(plan.plan_id) is False  # CAS: already applied
    assert plans.unapplied(user_id) == []
    assert plans.get(plan.plan_id).status == "applied"

    rank_id = launched[0].rank_id
    assert store.set_rank_status(rank_id, RankStatus.RUNNING, [RankStatus.LAUNCHING]) is True
    assert store.set_rank_status(rank_id, RankStatus.RUNNING, [RankStatus.LAUNCHING]) is False

    mine = next(r for r in store.running_jobs(user_id) if r.job.job_id == job.job_id)
    assert len(mine.ranks) == 2
    assert sum(rank.n_replicas for rank in mine.ranks) == 3
    assert {rank.role for rank in mine.ranks} == {RankRole.PREFILL, RankRole.DECODE}


def test_rank_requires_positive_replica_count(
    store: JobStore, pg_client: PostgresClient, user_id: str
):
    job = store.submit(Job(user_id=user_id, kind=JobKind.BATCH))

    with pytest.raises(ValueError, match="greater than or equal to 1"):
        Rank(
            job_id=job.job_id,
            role=RankRole.AGGREGATE,
            shape_json={"gpu": "H100", "count": 8},
            n_replicas=0,
        )

    now = datetime.now(UTC)
    with pytest.raises(IntegrityError), pg_client.begin() as s:
        s.add(
            RankRow(
                rank_id=new_rank_id(),
                job_id=job.job_id,
                role="aggregate",
                shape_json={},
                n_replicas=0,
                status="launching",
                created_at=now,
                updated_at=now,
            )
        )


def test_launch_ranks_upserts_without_changing_creation_or_job(
    store: JobStore, pg_client: PostgresClient, user_id: str
):
    job = store.submit(Job(user_id=user_id, kind=JobKind.ONLINE))
    other_job = store.submit(Job(user_id=user_id, kind=JobKind.ONLINE))
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    first = Rank(
        job_id=job.job_id,
        role=RankRole.PREFILL,
        shape_json={"gpu": "H100", "count": 8},
        n_replicas=2,
        created_at=created_at,
        updated_at=created_at,
    )
    protected = Rank(
        job_id=job.job_id,
        role=RankRole.DECODE,
        shape_json={"gpu": "H100", "count": 8},
        n_replicas=1,
    )
    store.launch_ranks([first, protected])

    with pytest.raises(ValueError, match="already belongs to another job"):
        store.launch_ranks(
            [
                first.model_copy(update={"n_replicas": 3}),
                protected.model_copy(update={"job_id": other_job.job_id}),
            ]
        )
    assert (
        next(rank for rank in store.ranks(job.job_id) if rank.rank_id == first.rank_id).n_replicas
        == 2
    )

    updated = first.model_copy(
        update={
            "role": RankRole.AGGREGATE,
            "shape_json": {"gpu": "H200", "count": 8},
            "n_replicas": 4,
            "status": RankStatus.RUNNING,
            "reason_code": "REORDERED_SWAP",
            "updated_at": datetime(2026, 1, 2, tzinfo=UTC),
            "created_at": datetime(2026, 1, 2, tzinfo=UTC),
        }
    )
    store.launch_ranks([updated])

    with pg_client.session() as s:
        row = s.get(RankRow, first.rank_id)
        assert row.job_id == job.job_id
        assert row.n_replicas == 4
        assert row.role == "aggregate"
        assert row.shape_json == {"gpu": "H200", "count": 8}
        assert row.status == "running"
        assert row.reason_code == "REORDERED_SWAP"
        assert row.created_at == created_at
        assert row.updated_at == datetime(2026, 1, 2, tzinfo=UTC)


# ----- Event log --------------------------------------------------------------


def test_event_log_cursor_and_consumer_ack(pg_client: PostgresClient):
    log = PostgresEventLog(pg_client)
    first = Event(type="job.submitted", user_id="usr_e", payload_json={"n": 1})
    second = Event(
        type="rank.failed",
        user_id="usr_e",
        rank_id="rank-event",
        payload_json={"rank_id": "rank-event"},
    )
    log.append(first)
    log.append(second)

    with pytest.raises(ValueError, match="rank_id must match"):
        log.append(
            Event(
                type="rank.failed",
                rank_id="rank-envelope",
                payload_json={"rank_id": "rank-payload"},
            )
        )

    assert [e.event_id for e in log.read_after(first.event_id)] == [second.event_id]
    assert second.event_id in {e.event_id for e in log.read_after(None, types={"rank.failed"})}

    consumer = f"koi-{first.event_id}"  # unique per run
    assert log.get_cursor(consumer) is None
    log.ack(consumer, first.event_id)
    assert log.get_cursor(consumer) == first.event_id
    assert [e.event_id for e in log.read_for_consumer(consumer)] == [second.event_id]
    log.ack(consumer, second.event_id)
    assert log.read_for_consumer(consumer) == []


# ----- GPU metric store (telemetry) --------------------------------------------


def test_gpu_metric_rank_reads_are_job_scoped(pg_client: PostgresClient) -> None:
    store = GpuMetricStore(pg_client)
    store.put_many(
        [
            GpuMetric(job_id="job-a", gpu_uuid="GPU-1", rank_id="rank_0"),
            GpuMetric(job_id="job-a", gpu_uuid="GPU-2", rank_id="rank_0"),
            # The same rank_id under another job must not leak in.
            GpuMetric(job_id="job-b", gpu_uuid="GPU-9", rank_id="rank_0"),
        ]
    )

    rows = store.rows_for_rank("job-a", "rank_0")
    assert sorted(r.gpu_uuid for r in rows) == ["GPU-1", "GPU-2"]
    assert {row.gpu_uuid for row in store.latest()} >= {"GPU-1", "GPU-2", "GPU-9"}
    assert store.rows_for_rank("job-b", "rank_0")[0].gpu_uuid == "GPU-9"
    assert store.rows_for_rank("job-c", "rank_0") == []


# ----- Model catalog store ------------------------------------------------------


def test_model_catalog_store_replace_get_and_warmup_helpers(pg_client: PostgresClient) -> None:
    store = ModelCatalogStore(pg_client)
    assert store.get("Qwen/Qwen3-0.6B") is None
    # No row yet: the warmup getter still returns the hardcoded default.
    assert store.get_min_chain_warmup_minutes("Qwen/Qwen3-0.6B") == 10.0

    store.replace(
        ModelCatalog(
            model_id="Qwen/Qwen3-0.6B",
            num_hidden_layers=28,
            is_moe=False,
            chunked_prefill_enable=True,
            max_num_seq=[{"gpu_type": "L4", "value": 64}],
        )
    )
    fetched = store.get("Qwen/Qwen3-0.6B")
    assert fetched is not None
    assert fetched.num_hidden_layers == 28
    assert fetched.chunked_prefill_enable is True
    assert fetched.max_num_seq == [{"gpu_type": "L4", "value": 64}]
    assert fetched.min_chain_warmup_time == 10.0

    # set_min_chain_warmup_minutes patches only that field.
    store.set_min_chain_warmup_minutes("Qwen/Qwen3-0.6B", 20.0)
    assert store.get_min_chain_warmup_minutes("Qwen/Qwen3-0.6B") == 20.0
    refetched = store.get("Qwen/Qwen3-0.6B")
    assert refetched is not None
    assert refetched.num_hidden_layers == 28  # untouched by the patch
    assert refetched.max_num_seq == [{"gpu_type": "L4", "value": 64}]

    # replace is a full upsert (last-write-wins).
    store.replace(ModelCatalog(model_id="Qwen/Qwen3-0.6B", num_hidden_layers=99))
    assert store.get("Qwen/Qwen3-0.6B").num_hidden_layers == 99  # type: ignore[union-attr]


# ----- Evidence store (Koi tick history) --------------------------------------


def _evidence_row(tick: int, job_id: str, rank_id: str) -> EvidenceRow:
    row_id = format_evidence_row_id(tick, job_id, rank_id)
    return EvidenceRow(
        row_id=row_id,
        tick=tick,
        deploy_timestamp_utc=float(tick),
        job_id=job_id,
        rank_id=rank_id,
        env_label=("reserved", "aws", "us-east-1", "use1-az1", "H100"),
        X={"n": tick, "tps": float(tick)},
        V_observed_trajectory={"latency": [1.0]},
        V_predicted_trajectory={"latency": [1.1]},
        y_observed_trajectory={"cost": [0.5]},
        y_predicted={"cost": 0.48},
        y_observed_mean={"cost": 0.5},
        residuals_per_v={"latency": [0.0]},
        residuals_per_y={"cost": [0.02]},
        deployment_id=f"deploy-{tick}-{rank_id}",
        evidence_available_timestamp_utc=float(tick) + 0.5,
        prediction_lineage={
            "schema_version": 3,
            "composite_version": "koi-surrogate-v3:test",
        },
    )


def _rich_evidence_row(
    tick: int,
    job_id: str,
    rank_id: str,
    *,
    env_label=("reserved", "aws", "us-east-1", "use1-az1", "H100"),
    workload_type: str = "online",
    mechanism_ids: list[str] | None = None,
    edge_ids: list[str] | None = None,
) -> EvidenceRow:
    row = _evidence_row(tick, job_id, rank_id)
    row.env_label = env_label
    row.X["type"] = workload_type
    row.mechanism_ids = list(mechanism_ids or [])
    row.icp_result_per_edge = dict.fromkeys(edge_ids or [], "accept")
    row.q_label_per_mechanism = dict.fromkeys(row.mechanism_ids, "Q1")
    return row


def test_evidence_store_recent_ticks(pg_client: PostgresClient, user_id: str):
    store = EvidenceStore(pg_client)
    job_id = new_job_id()

    for tick in range(1, 13):
        store.put(user_id, _evidence_row(tick, job_id, "prefill-0"))

    recent = store.recent(user_id, last_n_ticks=10)
    assert {r.tick for r in recent} == set(range(3, 13))
    assert len(recent) == 10
    assert [row.tick for row in store.latest(user_id, limit=3)] == [10, 11, 12]
    assert [row.tick for row in store.latest_before(user_id, 10.0, limit=3)] == [7, 8, 9]

    fetched = store.get(format_evidence_row_id(12, job_id, "prefill-0"))
    assert fetched is not None and fetched.X == {"n": 12, "tps": 12.0}
    assert fetched.deployment_id == "deploy-12-prefill-0"
    assert fetched.evidence_available_timestamp_utc == 12.5
    assert fetched.prediction_lineage == {
        "schema_version": 3,
        "composite_version": "koi-surrogate-v3:test",
    }


def test_evidence_store_query_helpers(pg_client: PostgresClient, user_id: str):
    store = EvidenceStore(pg_client)
    job_a, job_b = new_job_id(), new_job_id()
    env_a = ("reserved", "aws", "us-east-1", "use1-az1", "H100")
    env_b = ("reserved", "aws", "us-west-2", "usw2-az1", "A100")

    rows = [
        _rich_evidence_row(
            1,
            job_a,
            "rank-0",
            env_label=env_a,
            workload_type="online",
            mechanism_ids=["M1"],
            edge_ids=["e1"],
        ),
        _rich_evidence_row(
            2,
            job_a,
            "rank-0",
            env_label=env_b,
            workload_type="batch",
            mechanism_ids=["M1", "M2"],
            edge_ids=["e1", "e2"],
        ),
        _rich_evidence_row(
            3,
            job_b,
            "rank-1",
            env_label=env_a,
            workload_type="online",
            mechanism_ids=["M2"],
            edge_ids=["e2"],
        ),
    ]
    store.put_many(user_id, rows)

    assert store.current_tick(user_id) == 3
    assert [r.row_id for r in store.rows_in_window(user_id, 1, 2)] == [
        rows[0].row_id,
        rows[1].row_id,
    ]
    assert [r.row_id for r in store.rows_for_job(user_id, job_a)] == [
        rows[0].row_id,
        rows[1].row_id,
    ]
    assert [r.row_id for r in store.rows_for_rank(user_id, job_a, "rank-0")] == [
        rows[0].row_id,
        rows[1].row_id,
    ]
    assert [r.row_id for r in store.rows_for_edge(user_id, "e1")] == [
        rows[0].row_id,
        rows[1].row_id,
    ]
    assert [r.row_id for r in store.rows_for_edge(user_id, "e1", limit=1)] == [rows[1].row_id]
    assert [r.row_id for r in store.rows_for_mechanism(user_id, "M2")] == [
        rows[1].row_id,
        rows[2].row_id,
    ]
    assert [r.row_id for r in store.rows_for_environment(user_id, env_a)] == [
        rows[0].row_id,
        rows[2].row_id,
    ]
    assert [r.row_id for r in store.recently_decided(user_id, 1, tick=3)] == [
        rows[1].row_id,
        rows[2].row_id,
    ]
    assert [r.row_id for r in store.retrieve_similar_rows(user_id, {"type": "online"})] == [
        rows[0].row_id,
        rows[2].row_id,
    ]


# ----- GPU metrics ------------------------------------------------------------


def test_gpu_metric_koi_window_queries_are_user_job_rank_scoped(
    pg_client: PostgresClient, user_id: str
):
    store = GpuMetricStore(pg_client)
    other_user = new_user_id()
    job_a, job_b, other_job = new_job_id(), new_job_id(), new_job_id()
    rank_a0, rank_a1, rank_b, other_rank = (
        new_rank_id(),
        new_rank_id(),
        new_rank_id(),
        new_rank_id(),
    )
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC)
    t3 = datetime(2026, 1, 1, 0, 0, 3, tzinfo=UTC)
    t4 = datetime(2026, 1, 1, 0, 0, 4, tzinfo=UTC)

    with pg_client.begin() as s:
        s.add(UserRow(user_id=other_user, name="gpu-metric-other", created_at=t0))
    with pg_client.begin() as s:
        for uid, jid in ((user_id, job_a), (user_id, job_b), (other_user, other_job)):
            s.add(
                JobRow(
                    job_id=jid,
                    user_id=uid,
                    kind="online",
                    spec_json={},
                    input_source={},
                    output_target={},
                    status="running",
                    created_at=t0,
                )
            )
    # Separate transaction: ranks FK jobs, and without ORM relationships
    # SQLAlchemy does not order bare-FK inserts within one flush.
    with pg_client.begin() as s:
        for rank_id, jid in (
            (rank_a0, job_a),
            (rank_a1, job_a),
            (rank_b, job_b),
            (other_rank, other_job),
        ):
            s.add(
                RankRow(
                    rank_id=rank_id,
                    job_id=jid,
                    role="aggregate",
                    shape_json={"count": 1},
                    n_replicas=1,
                    status="running",
                    created_at=t0,
                    updated_at=t0,
                )
            )

    def metric(metric_id: str, job_id: str, rank_id: str | None, ts: datetime) -> GpuMetric:
        return GpuMetric(
            metric_id=metric_id,
            ts=ts,
            job_id=job_id,
            gpu_uuid=f"gpu-{metric_id}",
            rank_id=rank_id,
            chain_index=0,
            throughput_token_per_sec=1.0,
        )

    store.put_many(
        [
            metric("metric-rank-0", job_a, rank_a0, t1),
            metric("metric-rank-1", job_a, rank_a1, t2),
            metric("metric-other-job", job_b, rank_b, t1),
            metric("metric-other-user", other_job, other_rank, t1),
            metric("metric-mismatched-job", job_b, rank_a0, t1),
            metric("metric-no-rank", job_a, None, t1),
            metric("metric-outside-window", job_a, rank_a0, t4),
        ]
    )

    assert [m.metric_id for m in store.rows_for_job_window(user_id, job_a, t0, t3)] == [
        "metric-rank-0",
        "metric-rank-1",
    ]
    assert [m.metric_id for m in store.rows_for_rank_window(user_id, job_a, rank_a0, t0, t3)] == [
        "metric-rank-0"
    ]
    assert store.rows_for_job_window(user_id, other_job, t0, t3) == []


# ----- Resource map (Postgres) ------------------------------------------------


def _sample_resource_map(total_instances: int) -> ResourceMap:
    return ResourceMap(
        market=["reserved"],
        clouds={
            "aws": Cloud(
                regions={
                    "us-east-2": Region(
                        zones={
                            "use2-az3": Zone(
                                network_fabrics={
                                    "efa-cluster-a": NetworkFabric(
                                        fabric_type="efa",
                                        gpu_direct_rdma=True,
                                        machine_pools={
                                            "g6e.12xlarge": MachinePool(
                                                instance_family="g6",
                                                gpu_type="L40S",
                                                gpus_per_instance=4,
                                                total_instances=total_instances,
                                                price_per_instance_hour=10.49,
                                            )
                                        },
                                    )
                                }
                            )
                        }
                    )
                }
            )
        },
    )


def _g6e_pool(resource_map: ResourceMap) -> MachinePool:
    return (
        resource_map.clouds["aws"]
        .regions["us-east-2"]
        .zones["use2-az3"]
        .network_fabrics["efa-cluster-a"]
        .machine_pools["g6e.12xlarge"]
    )


def test_resource_map_store_postgres(pg_client: PostgresClient, user_id: str):
    store = ResourceMapStore(pg_client, user_id=user_id)

    assert store.get().version == 0
    assert store.get().clouds == {}

    first = store.replace(_sample_resource_map(total_instances=5))
    assert first.version == 1
    assert _g6e_pool(first).total_instances == 5
    assert first.scheduling_summary()["reserved|aws|us-east-2|use2-az3|L40S"]["total"] == 20

    second = store.replace(_sample_resource_map(total_instances=3))
    assert second.version == 2
    assert _g6e_pool(store.get()).total_instances == 3

    other = ResourceMapStore(pg_client, user_id=new_user_id())
    assert other.get().version == 0


# ----- Causal graph (Koi topology + confidence) --------------------------------


def test_causal_graph_store_postgres(pg_client: PostgresClient, user_id: str):
    store = CausalGraphStore(pg_client, user_id=user_id)
    assert store.is_empty()

    nodes = {
        "tp": CausalNode(node_id="tp", node_type="X"),
        "gpu_mem": CausalNode(node_id="gpu_mem", node_type="V"),
    }
    edge_id = "tp->gpu_mem"
    edges = {
        edge_id: CausalEdge(
            edge_id=edge_id,
            src="tp",
            dst="gpu_mem",
            src_type="X",
            dst_type="V",
        )
    }
    edge_metadata = {
        edge_id: EdgeMetadata(edge_id=edge_id, alpha=1.0, beta=1.0),
    }
    mechanism_id = "M_demo"
    mechanisms = {
        mechanism_id: CausalMechanism(
            mechanism_id=mechanism_id,
            name="tp_memory_pressure",
            edge_ids=[edge_id],
            scope={"x": ["tp"], "v": ["gpu_mem"]},
            narrative="tensor parallelism affects GPU memory",
        )
    }
    mechanism_metadata = {
        mechanism_id: MechanismMetadata(mechanism_id=mechanism_id),
    }

    # Nodes and edges are seeded outside the store (external seeder); the
    # store itself only loads them and syncs metadata. Simulate the seed by
    # writing ORM rows directly via the converters.
    with pg_client.begin() as s:
        for node in nodes.values():
            s.add(node_to_row(user_id, node))
        for edge in edges.values():
            s.add(edge_to_row(user_id, edge, edge_metadata[edge.edge_id]))
    store.sync_mechanisms(mechanisms, mechanism_metadata)

    loaded_nodes = store.load_nodes()
    loaded_edges, loaded_edge_meta = store.load_edges()
    loaded_mechs, loaded_mech_meta = store.load_mechanisms()

    assert loaded_nodes["tp"].node_type == "X"
    assert loaded_edges[edge_id].src == "tp"
    assert loaded_edge_meta[edge_id].alpha == 1.0

    loaded_edge_meta[edge_id].alpha = 2.5
    loaded_edge_meta[edge_id].visit_count = 3
    loaded_edge_meta[edge_id].envs_seen.add(("reserved", "aws", "us-east-1", "use1-az1", "H100"))
    store.sync_edge_metadata(loaded_edge_meta)

    _, reloaded_meta = store.load_edges()
    assert reloaded_meta[edge_id].alpha == 2.5
    assert reloaded_meta[edge_id].visit_count == 3
    assert (
        "reserved",
        "aws",
        "us-east-1",
        "use1-az1",
        "H100",
    ) in reloaded_meta[edge_id].envs_seen

    loaded_mechs[mechanism_id].status = "archived"
    loaded_mechs[mechanism_id].archived_reason = "superseded"
    loaded_mech_meta[mechanism_id].beta = 0.5
    store.sync_mechanisms(loaded_mechs, loaded_mech_meta)

    reloaded_mechs, reloaded_mech_meta = store.load_mechanisms()
    assert reloaded_mechs[mechanism_id].name == "tp_memory_pressure"
    assert reloaded_mechs[mechanism_id].status == "archived"
    assert reloaded_mech_meta[mechanism_id].beta == 0.5
