"""Cross-channel completion reaches the web SSE stream (FEAT-777 AC-2, AC-3)."""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest

from parrot.auth.oauth2.events import ConnectionEvent, ConnectionEventPublisher
from parrot.services.connection_push import CHANNEL_TEMPLATE, RedisConnectionPush

pytestmark = pytest.mark.asyncio

REDIS_TEST_URL = "redis://localhost:6379/15"


async def _wait_for_numsub(push: RedisConnectionPush, channel: str, expected: int) -> None:
    """Wait for Redis pub/sub subscriptions to become visible."""
    deadline = asyncio.get_running_loop().time() + 2
    while True:
        subscriptions = await push._redis.pubsub_numsub(channel)
        if subscriptions[0][1] == expected:
            return
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail(f"Expected {expected} subscribers on {channel}, got {subscriptions!r}")
        await asyncio.sleep(0.01)


async def test_e2e_web_panel_live_update() -> None:
    """A Telegram-originated completion reaches both web workers for one principal only."""
    publisher_push = RedisConnectionPush(REDIS_TEST_URL)
    subscriber_one = RedisConnectionPush(REDIS_TEST_URL)
    subscriber_two = RedisConnectionPush(REDIS_TEST_URL)
    other_subscriber = RedisConnectionPush(REDIS_TEST_URL)
    for push in (publisher_push, subscriber_one, subscriber_two, other_subscriber):
        await push.start()
    try:
        await publisher_push._redis.ping()
    except Exception as exc:  # noqa: BLE001
        for push in (publisher_push, subscriber_one, subscriber_two, other_subscriber):
            await push.close()
        pytest.skip(f"Redis unreachable: {exc}")

    user_id = f"e2e-connections-{uuid.uuid4()}"
    other_user_id = f"e2e-connections-{uuid.uuid4()}"
    target_channel = CHANNEL_TEMPLATE.format(user_id=user_id)
    other_channel = CHANNEL_TEMPLATE.format(user_id=other_user_id)
    stream_one = subscriber_one.subscribe(user_id)
    stream_two = subscriber_two.subscribe(user_id)
    other_stream = other_subscriber.subscribe(other_user_id)
    receive_one = asyncio.create_task(anext(stream_one))
    receive_two = asyncio.create_task(anext(stream_two))
    receive_other = asyncio.create_task(anext(other_stream))
    try:
        await _wait_for_numsub(subscriber_one, target_channel, 1)
        await _wait_for_numsub(subscriber_two, target_channel, 1)
        await _wait_for_numsub(other_subscriber, other_channel, 1)
        publisher = ConnectionEventPublisher()
        publisher.add_sink(publisher_push)
        event = ConnectionEvent(
            kind="connection.completed",
            user_id=user_id,
            provider="jira",
            channel="telegram",
            account_id="account-1",
            display_name="Test Account",
            occurred_at=time.time(),
        )
        await publisher.publish(event)

        assert await asyncio.wait_for(receive_one, timeout=2) == event
        assert await asyncio.wait_for(receive_two, timeout=2) == event
        assert not receive_other.done(), "A different principal must not receive this event"
        assert set(event.model_dump()) == {
            "kind",
            "user_id",
            "canonical_identity",
            "tenant_id",
            "provider",
            "account_id",
            "display_name",
            "channel",
            "occurred_at",
            "reason",
        }
        assert "access_token" not in event.model_dump_json()
    finally:
        for task in (receive_one, receive_two, receive_other):
            if not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        for stream in (stream_one, stream_two, other_stream):
            await stream.aclose()
        for push in (publisher_push, subscriber_one, subscriber_two, other_subscriber):
            await push.close()
