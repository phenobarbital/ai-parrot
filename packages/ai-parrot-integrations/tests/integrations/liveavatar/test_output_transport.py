"""Unit tests for the cross-process output transport (FEAT-243, Q-deploy)."""

import json

import pytest

from parrot.integrations.liveavatar.output_transport import (
    DEFAULT_OUTPUT_CHANNEL,
    RedisBroadcastForwarder,
    run_output_subscriber,
)


class FakeRedis:
    def __init__(self):
        self.published = []
        self.closed = False

    async def publish(self, channel, data):
        self.published.append((channel, data))

    async def aclose(self):
        self.closed = True


class FakePubSub:
    def __init__(self, messages):
        self._messages = messages
        self.subscribed = []
        self.unsubscribed = []

    async def subscribe(self, channel):
        self.subscribed.append(channel)

    async def unsubscribe(self, channel):
        self.unsubscribed.append(channel)

    async def listen(self):
        for msg in self._messages:
            yield msg


class FakeRedisWithPubSub:
    def __init__(self, messages):
        self._pubsub = FakePubSub(messages)

    def pubsub(self):
        return self._pubsub


class FakeSocketManager:
    def __init__(self):
        self.calls = []

    async def broadcast_to_channel(self, channel, message, exclude_ws=None):
        self.calls.append((channel, message))


@pytest.mark.asyncio
async def test_forwarder_publishes_envelope_to_redis():
    redis = FakeRedis()
    fwd = RedisBroadcastForwarder(redis)

    await fwd.broadcast_to_channel("s1", {"type": "chart", "payload": {"k": 1}})

    assert len(redis.published) == 1
    channel, data = redis.published[0]
    assert channel == DEFAULT_OUTPUT_CHANNEL
    envelope = json.loads(data)
    assert envelope == {"channel": "s1", "message": {"type": "chart", "payload": {"k": 1}}}


@pytest.mark.asyncio
async def test_forwarder_custom_channel_and_close():
    redis = FakeRedis()
    fwd = RedisBroadcastForwarder(redis, channel="custom:chan")

    await fwd.broadcast_to_channel("s2", {"x": 1})
    assert redis.published[0][0] == "custom:chan"

    await fwd.aclose()
    assert redis.closed is True


@pytest.mark.asyncio
async def test_subscriber_rebroadcasts_and_skips_noise():
    messages = [
        {"type": "subscribe", "data": 1},  # ignored
        {
            "type": "message",
            "data": json.dumps(
                {"channel": "s1", "message": {"type": "data", "payload": {}}}
            ),
        },
        {"type": "message", "data": "not-json"},  # logged + skipped, no crash
        {
            "type": "message",
            "data": json.dumps(
                {"channel": "s2", "message": {"type": "chart", "payload": {"v": 9}}}
            ),
        },
    ]
    redis = FakeRedisWithPubSub(messages)
    sm = FakeSocketManager()

    await run_output_subscriber(redis, sm, channel="c")

    # Both well-formed envelopes were re-broadcast on their target channels.
    assert sm.calls == [
        ("s1", {"type": "data", "payload": {}}),
        ("s2", {"type": "chart", "payload": {"v": 9}}),
    ]
    assert redis._pubsub.subscribed == ["c"]
    assert redis._pubsub.unsubscribed == ["c"]


def test_forwarder_from_url_builds_client():
    pytest.importorskip("redis")
    fwd = RedisBroadcastForwarder.from_url("redis://localhost:6379/0")
    assert isinstance(fwd, RedisBroadcastForwarder)
