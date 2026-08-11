"""ModelCatalog — per-model architecture, engine, and tuning defaults.

One row per Hugging Face model id in ``model_catalogs``, persisted via
``ModelCatalogStore``. Architecture fields come from the HuggingFace config;
engine-tunable fields default to vLLM's own defaults; a handful are Dynamo/
Tandemn placeholders hardcoded for now (noted per-field below). Consumers
(Orca's compiler, Koi's rank sizing) read this instead of re-deriving model
facts on every job.

Fields whose vLLM-recommended value depends on the GPU it runs on
(``max_num_seq``, ``max_num_batched_tokens``, ``block_size``,
``kvcache_dtype``) are a list of ``{"gpu_type": ..., "value": ...}`` entries,
one per profiled GPU type, rather than a single scalar.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.models._base import CanonicalModel, utc_now

# vLLM cold-start floor: hardcoded for now, not yet observed per model.
DEFAULT_MIN_CHAIN_WARMUP_MINUTES = 10.0

# Identity/bookkeeping fields live in their own columns; everything else is
# catalog data stored in catalog_json.
_IDENTITY_FIELDS = frozenset({"model_id", "updated_at"})


class ModelCatalog(CanonicalModel):
    model_id: str  # HuggingFace repo id, e.g. "Qwen/Qwen3-0.6B" -- the primary key
    updated_at: datetime = Field(default_factory=utc_now)

    # --- HuggingFace: architecture ---
    model_params_b: float | None = None
    model_size_gb: float | None = None
    num_hidden_layers: int | None = None
    hidden_size: int | None = None
    num_attn_heads: int | None = None
    num_kv_heads: int | None = None
    attn_heads_per_kv_head: int | None = None
    intermediate_size: int | None = None
    max_pos_embeddings: int | None = None
    vocab_size: int | None = None
    is_moe: bool | None = None
    num_routed_experts: int | None = None
    num_active_experts: int | None = None
    flops_per_param: float | None = None

    # --- vLLM engine ---
    engine_name: str | None = None
    engine_version: str | None = None
    attn_backend: str | None = None
    runtime_image: str | None = None  # dynamo-hardcoded
    max_num_seq: list[dict[str, Any]] = Field(default_factory=list)  # per GPU type
    max_num_batched_tokens: list[dict[str, Any]] = Field(default_factory=list)  # per GPU type
    gpu_mem_util: float = 0.85  # vLLM default
    max_model_len: int | None = None
    block_size: list[dict[str, Any]] = Field(default_factory=list)  # per GPU type
    kvcache_dtype: list[dict[str, Any]] = Field(default_factory=list)  # per GPU type

    # --- HuggingFace: weights / quantization ---
    weight_dtype: str | None = None
    weight_quantization_method: str = "none"
    weight_quantization_bits: int | None = None
    activation_quantization_method: str = "none"
    activation_dtype: str | None = None
    prefix_cache_enabled: bool | None = None
    chunked_prefill_enable: bool | None = None
    chunk_size: int = 100  # hardcoded
    sliding_window_size: int | None = None
    lmcache_enabled: bool = False  # hardcoded, off for now

    # --- vLLM: speculative decoding ---
    spec_decoding_enabled: bool | None = None
    draft_model_id: str = ""
    spec_decoding_method: str = "none"
    num_speculative_tokens: int = 0
    spec_acceptance_threshold: float = 0.0

    # --- Dynamo / vLLM: disaggregation, compilation, scheduling ---
    pd_enabled: bool = False  # hardcoded, off for now
    kv_transfer_method: str = "default"  # hardcoded (lmcache default)
    cuda_graph_enabled: bool = True  # hardcoded
    torch_compile_enabled: bool = True  # hardcoded
    scheduling_policy: str = "fcfs"  # vLLM default
    preemption_policy: str = "recompute"  # vLLM default
    max_chunked_steps_per_request: int = 2  # default
    router_policy: str = "kv_aware"  # default
    # vLLM cold-start floor, in minutes; hardcoded for now (see
    # ModelCatalogStore.get_min_chain_warmup_minutes/set_...).
    min_chain_warmup_time: float = DEFAULT_MIN_CHAIN_WARMUP_MINUTES


def model_catalog_to_json(catalog: ModelCatalog) -> dict[str, Any]:
    """Serialize a ``ModelCatalog``'s catalog fields for ``model_catalogs.catalog_json``."""
    body = catalog.model_dump(mode="json")
    for key in _IDENTITY_FIELDS:
        body.pop(key, None)
    return body


def model_catalog_from_row(
    *, model_id: str, updated_at: datetime, catalog: dict[str, Any]
) -> ModelCatalog:
    """Rebuild a ``ModelCatalog`` from indexed columns + ``catalog_json``."""
    return ModelCatalog(model_id=model_id, updated_at=updated_at, **catalog)
