"""Phase 1a smoke: both packages import cleanly and expose the expected surface."""

from __future__ import annotations


def test_system_data_imports():
    import tandemn_system_data

    assert tandemn_system_data.__version__ == "0.1.0"


def test_user_data_imports():
    import tandemn_user_data

    assert tandemn_user_data.__version__ == "0.1.0"


def test_clients_surface():
    from tandemn_system_data.clients import (
        PostgresClient,
        RedisStreamClient,
        S3BlobClient,
    )

    assert PostgresClient is not None
    assert RedisStreamClient is not None
    assert S3BlobClient is not None


def test_ids_prefix_registry():
    from tandemn_system_data.ids import PREFIXES

    # Spot-check the canonical prefixes from DATA_ARCHITECTURE.md
    assert PREFIXES["job"] == "job"
    assert PREFIXES["decision"] == "dec"
    assert PREFIXES["placement_alternative"] == "alt"
    assert PREFIXES["chain"] == "chain"
    assert PREFIXES["attempt"] == "att"
    assert PREFIXES["event"] == "evt"
