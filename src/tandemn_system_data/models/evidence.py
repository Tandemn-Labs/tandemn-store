"""Koi evidence row — learning/forensics contract.

One row captures what Koi saw and decided for one (tick, job, rank)
triple during a scheduler pass. Persisted via ``EvidenceStore`` (Postgres
``evidence_rows`` table) so Koi can read the last N ticks before each
pass. Not an Orca handoff type.

`rank_id` is a Koi-internal ladder-step key (e.g. a rung inside
`PlanAction.ladder`), not a FK to a `ranks` spine table. `tick` is Koi's
integer FSM counter for the pass, distinct from `tick_` ULID event
correlation IDs and from `plan_id`.

Opaque runtime objects (CUSUM/ICP handles) must be JSON-serializable
before ``EvidenceStore.put`` — see ``evidence_row_to_payload``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# (cloud, region, market, gpu_type)
EnvLabel = tuple[str, str, str, str]

_INDEXED_FIELDS = frozenset({"row_id", "tick", "deploy_timestamp_utc", "job_id", "rank_id"})


def format_evidence_row_id(tick: int, job_id: str, rank_id: str) -> str:
    """Canonical row_id: ``{tick}_{job_id}_{rank_id}``."""
    return f"{tick}_{job_id}_{rank_id}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return tolist()
    return str(value)


def evidence_row_to_payload(row: EvidenceRow) -> dict[str, Any]:
    """Serialize an ``EvidenceRow`` for ``evidence_rows.payload_json``."""
    body = asdict(row)
    for key in _INDEXED_FIELDS:
        body.pop(key, None)
    return _json_safe(body)


def evidence_payload_from_row(
    *,
    row_id: str,
    tick: int,
    deploy_timestamp_utc: float,
    job_id: str,
    rank_id: str,
    payload: dict[str, Any],
) -> EvidenceRow:
    """Rehydrate an ``EvidenceRow`` from indexed columns + payload JSON."""
    env = payload.get("env_label", ["", "", "", ""])
    if isinstance(env, list):
        env_label: EnvLabel = (env[0], env[1], env[2], env[3])
    else:
        env_label = ("", "", "", "")
    return EvidenceRow(
        row_id=row_id,
        tick=tick,
        deploy_timestamp_utc=deploy_timestamp_utc,
        job_id=job_id,
        rank_id=rank_id,
        env_label=env_label,
        X=payload.get("X", {}),
        W_observed=payload.get("W_observed", {}),
        V_observed_trajectory=payload.get("V_observed_trajectory", {}),
        V_predicted_trajectory=payload.get("V_predicted_trajectory", {}),
        y_observed_trajectory=payload.get("y_observed_trajectory", {}),
        y_predicted=payload.get("y_predicted", {}),
        y_observed_mean=payload.get("y_observed_mean", {}),
        residuals_per_v=payload.get("residuals_per_v", {}),
        residuals_per_y=payload.get("residuals_per_y", {}),
        mechanism_ids=payload.get("mechanism_ids", []),
        cusum_per_mechanism=_tuple_dict(payload.get("cusum_per_mechanism", {})),
        q_label_per_mechanism=payload.get("q_label_per_mechanism", {}),
        icp_result_per_edge=payload.get("icp_result_per_edge", {}),
        w_t_snapshot=payload.get("w_t_snapshot", {}),
        z_star_snapshot=payload.get("z_star_snapshot", {}),
        J_realized=float(payload.get("J_realized", 0.0)),
        sigma_realized=float(payload.get("sigma_realized", 0.0)),
        theory_blob=payload.get("theory_blob"),
    )


def _tuple_dict(raw: dict[str, Any]) -> dict[str, tuple[object, object]]:
    out: dict[str, tuple[object, object]] = {}
    for key, value in raw.items():
        if isinstance(value, list) and len(value) == 2:
            out[key] = (value[0], value[1])
    return out


@dataclass
class EvidenceRow:
    row_id: str  # f"{tick}_{job_id}_{rank_id}"
    tick: int  # integer FSM tick id
    deploy_timestamp_utc: float  # forensics; replay anchoring
    job_id: str
    rank_id: str
    env_label: EnvLabel  # (cloud, region, market, gpu_type)
    X: dict[str, object]  # ~60 decision variables
    W_observed: dict[str, float]  # 22 workload features
    # Values are np.ndarray at runtime in Koi; Any keeps numpy out of this package.
    V_observed_trajectory: dict[str, Any]  # sub-tick V samples (all measured V's)
    V_predicted_trajectory: dict[str, Any]  # surrogate's V_hat(t)
    y_observed_trajectory: dict[str, Any]  # sub-tick Y samples — Y-CUSUM input
    y_predicted: dict[str, float]  # surrogate's y_hat (scalar; CUSUM broadcasts)
    y_observed_mean: dict[str, float]  # mean of y_observed_trajectory per obj
    residuals_per_v: dict[str, Any]  # V_obs - V_pred — ICP + CUSUM recalibration
    residuals_per_y: dict[str, Any]  # y_obs - y_hat — ICP + DRO coverage tracking
    mechanism_ids: list[str] = field(default_factory=list)  # scope matches (incl. committed)
    cusum_per_mechanism: dict[str, tuple[object, object]] = field(default_factory=dict)
    q_label_per_mechanism: dict[str, object | None] = field(
        default_factory=dict
    )  # None where any ICP=UNDECIDED
    icp_result_per_edge: dict[str, object] = field(default_factory=dict)
    w_t_snapshot: dict[str, float] = field(default_factory=dict)  # Tchebycheff weights
    z_star_snapshot: dict[str, float] = field(default_factory=dict)
    J_realized: float = 0.0  # achieved Tchebycheff scalar
    sigma_realized: float = 0.0
    theory_blob: str | None = None
