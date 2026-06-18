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
        "market": "reserved",
        "cloud": "aws",
        "region": "us-east-2",
        "zone": "use2-az3",
        "pools": [
            {
                "fabric_id": "efa-cluster-a",
                "fabric_type": "efa",
                "gpu_direct_rdma": True,
                "instance_type": "p4d.24xlarge",
                "instance_family": "p4d",
                "total": 80,
                "total_instances": 10,
                "gpus_per_instance": 8,
                "price_per_instance_hour": 32.77,
            }
        ],
    }


def test_scheduling_summary_aggregates_colliding_pools():
    """Two A100 pools (different fabric/instance type) in the same zone
    share one env_key: totals sum and each pool is preserved in ``pools``."""
    rm = ResourceMap(
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
                                                gpus_per_instance=8,
                                                total_instances=10,
                                                price_per_instance_hour=32.77,
                                            ),
                                        },
                                    ),
                                    "efa-cluster-b": NetworkFabric(
                                        fabric_type="efa",
                                        gpu_direct_rdma=True,
                                        machine_pools={
                                            "p4de.24xlarge": MachinePool(
                                                instance_family="p4de",
                                                gpu_type="A100",
                                                gpus_per_instance=8,
                                                total_instances=5,
                                                price_per_instance_hour=36.00,
                                            ),
                                        },
                                    ),
                                }
                            )
                        }
                    )
                }
            )
        },
    )

    entry = rm.scheduling_summary()["reserved|aws|us-east-2|use2-az3|A100"]
    assert entry["total"] == 120  # 80 + 40, neither overwritten
    assert entry["total_instances"] == 15
    assert {p["instance_type"] for p in entry["pools"]} == {
        "p4d.24xlarge",
        "p4de.24xlarge",
    }
    assert {p["fabric_id"] for p in entry["pools"]} == {
        "efa-cluster-a",
        "efa-cluster-b",
    }
    assert {p["price_per_instance_hour"] for p in entry["pools"]} == {32.77, 36.00}


def test_resource_map_json_round_trip():
    original = _efa_map()
    restored = ResourceMap.model_validate_json(original.model_dump_json())
    assert restored == original
