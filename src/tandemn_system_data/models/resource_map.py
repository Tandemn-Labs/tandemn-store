"""ResourceMap — Orca's live hierarchical capacity view.

One Postgres row per ``user_id`` in ``resource_maps`` (``pools_json`` holds
``capacity_type`` + ``clouds``; monotonic ``version`` on the row). Orca
``replace``s; Koi ``get``s. ``available_instances`` is the schedulable
counter Orca updates on place / preempt / finish.
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
    available_instances: int
    intra_machine_interconnect: IntraMachineInterconnect | None = None

    @property
    def total_gpus(self) -> int:
        return self.total_instances * self.gpus_per_instance

    @property
    def available_gpus(self) -> int:
        return self.available_instances * self.gpus_per_instance


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
    capacity_type: list[str] = Field(default_factory=lambda: ["reserved"])
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

        env_key is ``cloud|region|zone|gpu_type``. Values include free/total
        GPU counts plus fabric and instance metadata.
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
            env_key = "|".join((cloud_id, region_id, zone_id, pool.gpu_type))
            summary[env_key] = {
                "free": pool.available_gpus,
                "total": pool.total_gpus,
                "available_instances": pool.available_instances,
                "total_instances": pool.total_instances,
                "gpu_type": pool.gpu_type,
                "cloud": cloud_id,
                "region": region_id,
                "zone": zone_id,
                "fabric_id": fabric_id,
                "instance_type": instance_type,
                "fabric_type": fabric.fabric_type,
                "gpu_direct_rdma": fabric.gpu_direct_rdma,
            }
        return summary
