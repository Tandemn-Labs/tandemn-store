"""GpuMetric — one GPU/inference telemetry sample.

One row per (deployment, GPU) per collector tick, persisted via
``GpuMetricStore`` (Postgres ``gpu_metrics`` table). The collector lives in
``tandemn-system`` (Orca): it polls Prometheus, computes the 28 tracked
metrics, and writes rows here. Append-only timeseries; not an Orca handoff
type.

The 28 metric fields are all optional: several are topology- or config-gated
(NVLink/comm/expert metrics need multi-GPU/TP>1/PP>1/MoE; ``sm_utilization``
needs extra DCGM counters) and are ``None`` when the current deployment does
not produce them. ``to_metrics`` / ``from_row`` move the metric fields in and
out of the ``metrics_json`` JSONB column.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.ids import new_gpu_metric_id
from tandemn_system_data.models._base import CanonicalModel, utc_now

# Identity/index fields live in their own columns; everything else is a metric
# value stored in metrics_json.
_IDENTITY_FIELDS = frozenset(
    {
        "metric_id",
        "ts",
        "deployment_id",
        "gpu_uuid",
        "rank_id",
        "chain_id",
        "local_rank",
        "role",
        "node_name",
        "instance_type",
        "model_name",
    }
)


class GpuMetric(CanonicalModel):
    metric_id: str = Field(default_factory=new_gpu_metric_id)
    ts: datetime = Field(default_factory=utc_now)
    # None for a GPU no worker owns (idle capacity on a tracked node).
    deployment_id: str | None = None
    gpu_uuid: str
    # Coarse -> fine: rank (ladder rung) > chain (a DP replica; the canonical
    # chains.chain_id when resolvable, else the worker pod name) > local_rank
    # (GPU index within the chain). All None for a GPU no chain owns.
    rank_id: str | None = None
    chain_id: str | None = None
    local_rank: str | None = None
    # PD-disaggregation role: "prefill" | "decode" | None (aggregated).
    role: str | None = None
    node_name: str | None = None
    instance_type: str | None = None
    model_name: str | None = None

    # --- GPU hardware (DCGM) ---
    gpu_mem_used_fraction: float | None = None
    vram_headroom_gb: float | None = None
    sm_utilization: float | None = None
    mem_bandwidth_utilization: float | None = None
    pcie_tput_observed: float | None = None
    nvlink_tput_observed: float | None = None

    # --- vLLM engine ---
    p99_ttft_ms: float | None = None
    p99_tpot_ms: float | None = None
    throughput_token_per_sec: float | None = None
    live_batch_size: float | None = None
    depth_req_q: float | None = None
    kv_cache_util: float | None = None
    kvcache_hit_rate: float | None = None
    input_length_observed: float | None = None
    output_length_observed: float | None = None
    prefill_iteration_counts_per_second: float | None = None
    decode_itr_counts_per_second: float | None = None

    # --- derived / composite ---
    slo_margin: float | None = None
    kv_pressure_score: float | None = None
    cost_per_token: float | None = None
    activation_mem_pressure: float | None = None
    pd_inbalance: float | None = None

    # --- topology-gated (multi-GPU / TP>1 / PP>1 / MoE) ---
    comm_overhead_pct: float | None = None
    per_tok_comm_bytes: float | None = None
    pipeline_bubble_fraction: float | None = None
    expert_inbalance: float | None = None
    dispatch_overhead_ms: float | None = None


def gpu_metric_to_metrics(metric: GpuMetric) -> dict[str, Any]:
    """Serialize a ``GpuMetric``'s metric values for ``gpu_metrics.metrics_json``."""
    body = metric.model_dump()
    for key in _IDENTITY_FIELDS:
        body.pop(key, None)
    return body


def gpu_metric_from_row(
    *,
    metric_id: str,
    ts: datetime,
    deployment_id: str | None,
    gpu_uuid: str,
    rank_id: str | None,
    chain_id: str | None,
    local_rank: str | None,
    role: str | None,
    node_name: str | None,
    instance_type: str | None,
    model_name: str | None,
    metrics: dict[str, Any],
) -> GpuMetric:
    """Rebuild a ``GpuMetric`` from indexed columns + ``metrics_json``."""
    return GpuMetric(
        metric_id=metric_id,
        ts=ts,
        deployment_id=deployment_id,
        gpu_uuid=gpu_uuid,
        rank_id=rank_id,
        chain_id=chain_id,
        local_rank=local_rank,
        role=role,
        node_name=node_name,
        instance_type=instance_type,
        model_name=model_name,
        **metrics,
    )
