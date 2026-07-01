"""Pydantic models for the canonical entities in DATA_ARCHITECTURE.md §5.

Re-exports every entity model and shared enum at the package level so
consumers can write `from tandemn_system_data.models import Job, Chain, ...`.
"""

from __future__ import annotations

from tandemn_system_data.models._base import CanonicalModel, utc_now
from tandemn_system_data.models.causal_graph import (
    CausalEdge,
    CausalMechanism,
    CausalNode,
    EdgeMetadata,
    MechanismMetadata,
    envs_seen_from_json,
    envs_seen_to_json,
)
from tandemn_system_data.models.chain import Chain
from tandemn_system_data.models.credentials import Credentials
from tandemn_system_data.models.enums import (
    ActionType,
    ChainRole,
    ChainStatus,
    JobKind,
    JobStatus,
    ReasonCode,
)
from tandemn_system_data.models.event import Event
from tandemn_system_data.models.event_consumer_offset import EventConsumerOffset
from tandemn_system_data.models.evidence import (
    EnvLabel,
    EvidenceRow,
    evidence_payload_from_row,
    evidence_row_to_payload,
    format_evidence_row_id,
)
from tandemn_system_data.models.gpu_metric import (
    GpuMetric,
    gpu_metric_from_row,
    gpu_metric_to_metrics,
)
from tandemn_system_data.models.hardware_catalog import (
    DEFAULT_HARDWARE_CATALOG_KEY,
    HardwareCatalog,
)
from tandemn_system_data.models.job import ChainAllocation, Job, RunningJob
from tandemn_system_data.models.plan import Plan, PlanAction
from tandemn_system_data.models.resource_map import (
    Cloud,
    IntraMachineInterconnect,
    MachinePool,
    NetworkFabric,
    Region,
    ResourceMap,
    Zone,
)
from tandemn_system_data.models.user import User

__all__ = [
    "DEFAULT_HARDWARE_CATALOG_KEY",
    "ActionType",
    "CanonicalModel",
    "CausalEdge",
    "CausalMechanism",
    "CausalNode",
    "Chain",
    "ChainAllocation",
    "ChainRole",
    "ChainStatus",
    "Cloud",
    "Credentials",
    "EdgeMetadata",
    "EnvLabel",
    "Event",
    "EventConsumerOffset",
    "EvidenceRow",
    "GpuMetric",
    "HardwareCatalog",
    "IntraMachineInterconnect",
    "Job",
    "JobKind",
    "JobStatus",
    "MachinePool",
    "MechanismMetadata",
    "NetworkFabric",
    "Plan",
    "PlanAction",
    "ReasonCode",
    "Region",
    "ResourceMap",
    "RunningJob",
    "User",
    "Zone",
    "envs_seen_from_json",
    "envs_seen_to_json",
    "evidence_payload_from_row",
    "evidence_row_to_payload",
    "format_evidence_row_id",
    "gpu_metric_from_row",
    "gpu_metric_to_metrics",
    "utc_now",
]
