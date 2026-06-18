"""ResourceMap — Orca's live hierarchical capacity view.

One Postgres row per ``user_id`` in ``resource_maps`` (``pools_json`` holds
``market`` + ``clouds``; monotonic ``version`` on the row). Orca
``replace``s; Koi ``get``s. Total capacity only — free/available capacity is
inferred from running jobs, not stored here.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

from pydantic import Field

from tandemn_system_data.models._base import CanonicalModel, utc_now


class IntraMachineInterconnect(CanonicalModel):
    type: str


class MachinePool(CanonicalModel):
    instance_family: str | None = None
    gpu_type: str
    gpu_memory_gb: int | None = None
    gpus_per_instance: int
    total_instances: int
    price_per_instance_hour: float | None = None
    intra_machine_interconnect: IntraMachineInterconnect | None = None

    @property
    def total_gpus(self) -> int:
        return self.total_instances * self.gpus_per_instance


class NetworkFabric(CanonicalModel):
    fabric_type: str
    gpu_direct_rdma: bool = False
    machine_pools: dict[str, MachinePool] = Field(default_factory=dict)


class Zone(CanonicalModel):
    network_fabrics: dict[str, NetworkFabric] = Field(default_factory=dict)


class Region(CanonicalModel):
    zones: dict[str, Zone] = Field(default_factory=dict)


class Cloud(CanonicalModel):
    regions: dict[str, Region] = Field(default_factory=dict)


class ResourceMap(CanonicalModel):
    version: int = 0
    updated_at: datetime = Field(default_factory=utc_now)
    market: list[str] = Field(default_factory=lambda: ["reserved"])
    clouds: dict[str, Cloud] = Field(default_factory=dict)

    def iter_machine_pools(
        self,
    ) -> Iterator[tuple[str, str, str, str, NetworkFabric, str, MachinePool]]:
        """Yield ``(cloud, region, zone, fabric_id, fabric, instance_type, pool)``."""
        for cloud_id, cloud in self.clouds.items():
            for region_id, region in cloud.regions.items():
                for zone_id, zone in region.zones.items():
                    for fabric_id, fabric in zone.network_fabrics.items():
                        for instance_type, pool in fabric.machine_pools.items():
                            yield (
                                cloud_id,
                                region_id,
                                zone_id,
                                fabric_id,
                                fabric,
                                instance_type,
                                pool,
                            )

    def scheduling_summary(self) -> dict[str, dict[str, Any]]:
        """Flat env_key -> GPU capacity for Koi placement checks.

        env_key is ``market|cloud|region|zone|gpu_type`` (one entry per
        market). Multiple machine pools can share an env_key (e.g. two A100
        pools on different fabrics/instance types in the same zone); their
        ``total`` / ``total_instances`` are summed and each pool's
        fabric/instance/price detail is preserved in the ``pools`` list.
        Free capacity is not stored — Koi infers it from running jobs.
        """
        summary: dict[str, dict[str, Any]] = {}
        for (
            cloud_id,
            region_id,
            zone_id,
            fabric_id,
            fabric,
            instance_type,
            pool,
        ) in self.iter_machine_pools():
            for market in self.market:
                env_key = "|".join((market, cloud_id, region_id, zone_id, pool.gpu_type))
                pool_detail = {
                    "fabric_id": fabric_id,
                    "fabric_type": fabric.fabric_type,
                    "gpu_direct_rdma": fabric.gpu_direct_rdma,
                    "instance_type": instance_type,
                    "instance_family": pool.instance_family,
                    "total": pool.total_gpus,
                    "total_instances": pool.total_instances,
                    "gpus_per_instance": pool.gpus_per_instance,
                    "price_per_instance_hour": pool.price_per_instance_hour,
                }
                entry = summary.get(env_key)
                if entry is None:
                    summary[env_key] = {
                        "total": pool.total_gpus,
                        "total_instances": pool.total_instances,
                        "gpu_type": pool.gpu_type,
                        "market": market,
                        "cloud": cloud_id,
                        "region": region_id,
                        "zone": zone_id,
                        "pools": [pool_detail],
                    }
                else:
                    entry["total"] += pool.total_gpus
                    entry["total_instances"] += pool.total_instances
                    entry["pools"].append(pool_detail)
        return summary
