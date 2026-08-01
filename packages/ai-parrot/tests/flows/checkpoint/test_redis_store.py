"""Tests for parrot.bots.flows.core.checkpoint.store.redis (TASK-2049).

Exercises the ephemeral tier against a real test Redis instance (latest
pointer, bounded history trimming, TTL, and the resume lease lifecycle).
Skipped cleanly when no Redis server is reachable.
"""
from datetime import UTC, datetime

import pytest
from parrot.bots.flows.core.checkpoint import ContextSnapshot, FlowCheckpoint
from parrot.bots.flows.core.checkpoint.store.redis import RedisCheckpointStore
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
from parrot.conf import REDIS_URL


def _redis_available() -> bool:
    """Best-effort check for a reachable Redis server (no asyncio needed)."""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(REDIS_URL)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_available(), reason="Redis is not reachable at REDIS_URL"
)


@pytest.fixture
def flow_definition() -> FlowDefinition:
    return FlowDefinition(
        flow="redis-store-test-flow",
        nodes=[NodeDefinition(id="start", type="start")],
    )


def make_checkpoint(
    flow_id: str,
    checkpoint_id: int,
    definition: FlowDefinition,
    status: str = "running",
) -> FlowCheckpoint:
    return FlowCheckpoint(
        flow_id=flow_id,
        flow_name=definition.flow,
        checkpoint_id=checkpoint_id,
        created_at=datetime.now(UTC),
        status=status,
        definition=definition,
        context=ContextSnapshot(initial_task="do the thing"),
    )


@pytest.fixture
async def redis_store():
    store = RedisCheckpointStore()
    yield store
    await store.close()


@pytest.mark.asyncio
async def test_redis_store_latest_history_trim_ttl(redis_store, flow_definition):
    flow_id = "test-flow-trim"
    await redis_store.delete_flow(flow_id)  # clean slate

    for i in range(1, 13):
        await redis_store.put(make_checkpoint(flow_id, i, flow_definition))

    latest = await redis_store.latest(flow_id)
    assert latest is not None
    assert latest.checkpoint_id == 12

    history = await redis_store.history(flow_id, limit=20)
    assert len(history) == 10
    assert history[0].checkpoint_id == 12
    assert history[-1].checkpoint_id == 3  # ids 1,2 trimmed beyond history=10

    await redis_store.delete_flow(flow_id)
    assert await redis_store.latest(flow_id) is None


@pytest.mark.asyncio
async def test_redis_store_get_specific_checkpoint(redis_store, flow_definition):
    flow_id = "test-flow-get"
    await redis_store.delete_flow(flow_id)

    await redis_store.put(make_checkpoint(flow_id, 1, flow_definition))
    await redis_store.put(make_checkpoint(flow_id, 2, flow_definition))

    cp = await redis_store.get(flow_id, 1)
    assert cp is not None
    assert cp.checkpoint_id == 1

    missing = await redis_store.get(flow_id, 999)
    assert missing is None

    await redis_store.delete_flow(flow_id)


@pytest.mark.asyncio
async def test_redis_lease_acquire_conflict_renew_expiry(redis_store):
    flow_id = "test-flow-lease"

    assert await redis_store.acquire_lease(flow_id, "holder-a", ttl=60)
    assert not await redis_store.acquire_lease(flow_id, "holder-b", ttl=60)

    assert await redis_store.renew_lease(flow_id, "holder-a", ttl=60)
    assert not await redis_store.renew_lease(flow_id, "holder-b", ttl=60)

    # holder-b cannot release holder-a's lease (no-op)
    await redis_store.release_lease(flow_id, "holder-b")
    assert not await redis_store.acquire_lease(flow_id, "holder-b", ttl=60)

    # holder-a releases; holder-b can now acquire
    await redis_store.release_lease(flow_id, "holder-a")
    assert await redis_store.acquire_lease(flow_id, "holder-b", ttl=60)

    await redis_store.release_lease(flow_id, "holder-b")


@pytest.mark.asyncio
async def test_redis_lease_expiry_allows_takeover(redis_store):
    flow_id = "test-flow-lease-expiry"

    assert await redis_store.acquire_lease(flow_id, "holder-a", ttl=1)
    import asyncio

    await asyncio.sleep(1.2)
    # holder-a's lease expired; holder-b can now take over
    assert await redis_store.acquire_lease(flow_id, "holder-b", ttl=60)

    await redis_store.release_lease(flow_id, "holder-b")


@pytest.mark.asyncio
async def test_redis_store_list_flows_filters_by_status(redis_store, flow_definition):
    flow_id_a = "test-flow-list-a"
    flow_id_b = "test-flow-list-b"
    await redis_store.delete_flow(flow_id_a)
    await redis_store.delete_flow(flow_id_b)

    await redis_store.put(make_checkpoint(flow_id_a, 1, flow_definition, status="running"))
    await redis_store.put(make_checkpoint(flow_id_b, 1, flow_definition, status="suspended"))

    suspended = await redis_store.list_flows(status="suspended")
    flow_ids = {f["flow_id"] for f in suspended}
    assert flow_id_b in flow_ids
    assert flow_id_a not in flow_ids

    await redis_store.delete_flow(flow_id_a)
    await redis_store.delete_flow(flow_id_b)
