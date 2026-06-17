"""Unit tests for hierarchical ResourceMap wire contract."""

from __future__ import annotations

from tandemn_system_data.models.resource_map import (
    Cloud,
    IntraMachineInterconnect,
    MachinePool,
    NetworkFabric,
    Region,
    ResourceMap,
    Zone,
)


def _efa_map(available_instances: int) -> ResourceMap:
    return ResourceMap(
        capacity_type=["reserved"],
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
                                            "p4d.24xlarge": MachinePool(
                                                instance_family="p4d",
                                                gpu_type="A100",
                                                gpu_memory_gb=40,
                                                gpus_per_instance=8,
                                                total_instances=10,
                                                available_instances=available_instances,
                                                intra_machine_interconnect=IntraMachineInterconnect(
                                                    type="nvlink_nvswitch"
                                                ),
                                            ),
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


def test_resource_map_scheduling_summary():
    summary = _efa_map(available_instances=7).scheduling_summary()
    assert summary["aws|us-east-2|use2-az3|A100"] == {
        "free": 56,
        "total": 80,
        "available_instances": 7,
        "total_instances": 10,
        "gpu_type": "A100",
        "cloud": "aws",
        "region": "us-east-2",
        "zone": "use2-az3",
        "fabric_id": "efa-cluster-a",
        "instance_type": "p4d.24xlarge",
        "fabric_type": "efa",
        "gpu_direct_rdma": True,
    }


def test_resource_map_json_round_trip():
    original = _efa_map(available_instances=3)
    restored = ResourceMap.model_validate_json(original.model_dump_json())
    assert restored == original
