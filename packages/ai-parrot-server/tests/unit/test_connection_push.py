"""Real-Redis tests for RedisConnectionPush (FEAT-777 M1). Skips when Redis db 15 is unreachable."""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest

from parrot.auth.oauth2.events import ConnectionEvent, ConnectionEventSink
from parrot.services.connection_push import CHANNEL_TEMPLATE, RedisConnectionPush

REDIS_TEST_URL = "redis://localhost:6379/15"


@pytest.fixture
async def push():
    """Yield a started push service when the local test Redis is reachable."""
    service = RedisConnectionPush(REDIS_TEST_URL)
    await service.start()
    try:
        await service._redis.ping()
    except Exception as exc:  # noqa: BLE001
        await service.close()
        pytest.skip(f"Redis unreachable: {exc}")
    yield service
    await service.close()


def _event(user_id: str) -> ConnectionEvent:
    """Build a connection event with a unique principal."""
    return ConnectionEvent(
        kind="connection.completed",
        user_id=user_id,
        provider="jira",
        channel="telegram",
        occurred_at=time.time(),
    )


async def _wait_for_numsub(push: RedisConnectionPush, channel: str, expected: int) -> None:
    """Wait briefly until Redis reports the expected number of channel subscribers."""
    deadline = asyncio.get_running_loop().time() + 2
    while True:
        subscriptions = await push._redis.pubsub_numsub(channel)
        if subscriptions[0][1] == expected:
            return
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail(f"Expected {expected} subscribers on {channel}, got {subscriptions!r}")
        await asyncio.sleep(0.01)


async def _next_message(pubsub):
    """Return the next Redis message while skipping subscription bookkeeping frames."""
    async for raw in pubsub.listen():
        if raw.get("type") == "message":
            return raw
    raise RuntimeError("Redis pubsub stream ended before a message arrived")


@pytest.mark.asyncio
async def test_redis_push_channel_per_principal(push) -> None:
    """deliver publishes an exact payload to only the target principal's channel."""
    user_a = f"connection-push-{uuid.uuid4()}"
    user_b = f"connection-push-{uuid.uuid4()}"
    channel_a = CHANNEL_TEMPLATE.format(user_id=user_a)
    channel_b = CHANNEL_TEMPLATE.format(user_id=user_b)
    subscriber_a = push.subscribe(user_a)
    subscriber_b = push.subscribe(user_b)
    receive_a = asyncio.create_task(anext(subscriber_a))
    receive_b = asyncio.create_task(anext(subscriber_b))
    raw_pubsub = push._redis.pubsub()

    try:
        await _wait_for_numsub(push, channel_a, 1)
        await _wait_for_numsub(push, channel_b, 1)
        await raw_pubsub.subscribe(channel_a)
        await _wait_for_numsub(push, channel_a, 2)

        event = _event(user_a)
        await push.deliver(event)

        received = await asyncio.wait_for(receive_a, timeout=2)
        raw = await asyncio.wait_for(_next_message(raw_pubsub), timeout=2)
        assert received == event
        assert raw["data"] == event.model_dump_json()
        assert not receive_b.done()
    finally:
        if not receive_a.done():
            receive_a.cancel()
            with pytest.raises(asyncio.CancelledError):
                await receive_a
        if not receive_b.done():
            receive_b.cancel()
            with pytest.raises(asyncio.CancelledError):
                await receive_b
        await subscriber_a.aclose()
        await subscriber_b.aclose()
        await raw_pubsub.unsubscribe(channel_a)
        await raw_pubsub.aclose()


@pytest.mark.asyncio
async def test_subscribe_unsubscribes_on_cancel(push) -> None:
    """Cancelling the consumer task unsubscribes from the principal's Redis channel."""
    user_id = f"connection-push-{uuid.uuid4()}"
    channel = CHANNEL_TEMPLATE.format(user_id=user_id)
    subscriber = push.subscribe(user_id)
    consumer = asyncio.create_task(anext(subscriber))

    await _wait_for_numsub(push, channel, 1)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer
    await _wait_for_numsub(push, channel, 0)
    await subscriber.aclose()


def test_is_a_connection_event_sink() -> None:
    """The push service structurally implements the event sink protocol."""
    assert isinstance(RedisConnectionPush(REDIS_TEST_URL), ConnectionEventSink)
    assert CHANNEL_TEMPLATE.format(user_id="7") == "parrot:connections:user:7"
