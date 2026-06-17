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


def _efa_map() -> ResourceMap:
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
                                            "p4d.24xlarge": MachinePool(
                                                instance_family="p4d",
                                                gpu_type="A100",
                                                gpu_memory_gb=40,
                                                gpus_per_instance=8,
                                                total_instances=10,
                                                price_per_instance_hour=32.77,
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
    summary = _efa_map().scheduling_summary()
    assert summary["reserved|aws|us-east-2|use2-az3|A100"] == {
        "total": 80,
        "total_instances": 10,
        "gpu_type": "A100",
        "price_per_instance_hour": 32.77,
        "market": "reserved",
        "cloud": "aws",
        "region": "us-east-2",
        "zone": "use2-az3",
        "fabric_id": "efa-cluster-a",
        "instance_type": "p4d.24xlarge",
        "fabric_type": "efa",
        "gpu_direct_rdma": True,
    }


def test_resource_map_json_round_trip():
    original = _efa_map()
    restored = ResourceMap.model_validate_json(original.model_dump_json())
    assert restored == original
