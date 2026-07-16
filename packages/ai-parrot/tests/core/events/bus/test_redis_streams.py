"""Tests for RedisStreamsBackend (FEAT-310, TASK-1789).

Unit tier uses a hand-rolled fake streams client (fakeredis is not in the
dependency set); the two-consumer end-to-end test is ``integration``-marked
and skips when no Redis is reachable.
"""
import asyncio
import json
import os
import time

import pytest

from parrot.core.events.bus.backends.base import TransportBackend
from parrot.core.events.bus.backends.redis_streams import RedisStreamsBackend
from parrot.core.events.bus.envelope import EventEnvelope


def make_envelope(topic: str = "app.job", **kwargs) -> EventEnvelope:
    return EventEnvelope(topic=topic, payload=kwargs.pop("payload", {"k": 1}), **kwargs)


async def wait_until(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.01)
    pytest.fail("condition not met within timeout")


# ---------------------------------------------------------------------------
# Fake Redis with minimal Streams semantics
# ---------------------------------------------------------------------------


class FakeStreamsRedis:
    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict]]] = {}
        # (stream, group) -> {"delivered": int, "pending": {id: [consumer, ts]}}
        self.groups: dict[tuple[str, str], dict] = {}
        self.kv: dict[str, str] = {}
        self.acked: list[tuple[str, str, str]] = []
        self._seq = 0

    async def xadd(self, name, fields, maxlen=None, approximate=True):
        self._seq += 1
        msg_id = f"{self._seq}-0"
        entries = self.streams.setdefault(name, [])
        entries.append((msg_id, dict(fields)))
        if maxlen is not None and len(entries) > maxlen:
            del entries[: len(entries) - maxlen]
        return msg_id

    async def xgroup_create(self, name, group, id="0", mkstream=False):
        if name not in self.streams:
            if not mkstream:
                raise Exception("NOGROUP no such stream")
            self.streams[name] = []
        key = (name, group)
        if key in self.groups:
            raise FakeResponseError("BUSYGROUP Consumer Group name already exists")
        self.groups[key] = {"delivered": 0, "pending": {}}

    async def xreadgroup(self, group, consumer, streams, count=None, block=None):
        results = []
        for stream in streams:
            g = self.groups.get((stream, group))
            if g is None:
                continue
            entries = self.streams.get(stream, [])
            new = entries[g["delivered"]:]
            if count:
                new = new[:count]
            if new:
                now = time.monotonic()
                for msg_id, _ in new:
                    g["pending"][msg_id] = [consumer, now]
                g["delivered"] += len(new)
                results.append((stream, list(new)))
        if not results and block:
            await asyncio.sleep(min(block / 1000, 0.02))
        return results

    async def xack(self, stream, group, msg_id):
        g = self.groups.get((stream, group))
        if g and msg_id in g["pending"]:
            del g["pending"][msg_id]
            self.acked.append((stream, group, msg_id))
            return 1
        return 0

    async def xautoclaim(
        self, name, group, consumer, min_idle_time, start_id="0-0", count=None
    ):
        g = self.groups.get((name, group))
        if g is None:
            return ["0-0", [], []]
        now = time.monotonic()
        claimed = []
        by_id = dict(self.streams.get(name, []))
        for msg_id, meta in list(g["pending"].items()):
            idle_ms = (now - meta[1]) * 1000
            if idle_ms >= min_idle_time and msg_id in by_id:
                g["pending"][msg_id] = [consumer, now]
                claimed.append((msg_id, by_id[msg_id]))
                if count and len(claimed) >= count:
                    break
        return ["0-0", claimed, []]

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    async def delete(self, key):
        return 1 if self.kv.pop(key, None) is not None else 0

    async def scan_iter(self, match=None):
        prefix = (match or "*").rstrip("*")
        for name in list(self.streams):
            if name.startswith(prefix):
                yield name

    async def close(self):
        pass


class FakeResponseError(Exception):
    pass


@pytest.fixture(autouse=True)
def _patch_response_error(monkeypatch):
    """Make the backend's BUSYGROUP check catch the fake's error type."""
    import parrot.core.events.bus.backends.redis_streams as mod
    monkeypatch.setattr(
        mod.aioredis, "ResponseError", FakeResponseError, raising=False
    )


@pytest.fixture
def fake_redis():
    return FakeStreamsRedis()


def make_backend(fake_redis, **overrides) -> RedisStreamsBackend:
    defaults = dict(
        client=fake_redis,
        consumer_name="test-consumer",
        block_ms=20,
        autoclaim_interval=0.05,
        min_idle_time_ms=50,
        stream_refresh_interval=0.01,
        dedup_ttl=60,
    )
    defaults.update(overrides)
    return RedisStreamsBackend(**defaults)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_streams_backend_satisfies_protocol(fake_redis):
    assert isinstance(make_backend(fake_redis), TransportBackend)


def test_requires_url_or_client():
    with pytest.raises(ValueError):
        RedisStreamsBackend()


async def test_streams_publish_consume_ack(fake_redis):
    backend = make_backend(fake_redis)
    received: list[EventEnvelope] = []

    async def consumer(envelope):
        received.append(envelope)

    env = make_envelope("app.job")
    await backend.publish(env)

    # stream-per-topic-class with the JSON wire format
    assert "parrot:stream:app" in fake_redis.streams
    _, fields = fake_redis.streams["parrot:stream:app"][0]
    assert EventEnvelope.from_dict(json.loads(fields["envelope"])) == env

    await backend.start_consumer(consumer)
    await wait_until(lambda: len(received) == 1)
    assert received[0] == env
    # ACKed exactly once in the happy path
    await wait_until(lambda: len(fake_redis.acked) == 1)
    stream, group, _ = fake_redis.acked[0]
    assert (stream, group) == ("parrot:stream:app", "parrot-bus")
    pending = fake_redis.groups[("parrot:stream:app", "parrot-bus")]["pending"]
    assert pending == {}
    await backend.close()


async def test_streams_autoclaim_reclaims_pending(fake_redis):
    env = make_envelope("app.crashed")
    # Seed: entry delivered to a consumer that died before ACK.
    await fake_redis.xadd(
        "parrot:stream:app", {"envelope": json.dumps(env.to_dict())}
    )
    await fake_redis.xgroup_create("parrot:stream:app", "parrot-bus", id="0")
    g = fake_redis.groups[("parrot:stream:app", "parrot-bus")]
    g["delivered"] = 1
    g["pending"]["1-0"] = ["dead-consumer", time.monotonic() - 10]  # stale

    backend = make_backend(fake_redis)
    received: list[EventEnvelope] = []

    async def consumer(envelope):
        received.append(envelope)

    await backend.start_consumer(consumer)
    # The sweeper reclaims + reprocesses + ACKs.
    await wait_until(lambda: len(received) == 1)
    assert received[0] == env
    await wait_until(lambda: ("parrot:stream:app", "parrot-bus", "1-0") in fake_redis.acked)
    assert g["pending"] == {}
    await backend.close()


async def test_streams_event_id_dedup(fake_redis):
    backend = make_backend(fake_redis)
    received: list[EventEnvelope] = []

    async def consumer(envelope):
        received.append(envelope)

    env = make_envelope("app.dup")
    # The same envelope lands on the stream twice (redelivery scenario).
    await backend.publish(env)
    await backend.publish(env)

    await backend.start_consumer(consumer)
    await wait_until(lambda: len(fake_redis.acked) == 2)  # both ACKed
    await asyncio.sleep(0.05)
    assert len(received) == 1  # processed once — dedup SET honored
    assert f"parrot:events:dedup:{env.event_id}" in fake_redis.kv
    await backend.close()


async def test_streams_failure_releases_dedup_and_keeps_pending(fake_redis):
    backend = make_backend(fake_redis, autoclaim_interval=999)  # sweeper idle
    calls: list[str] = []

    async def failing_consumer(envelope):
        calls.append(envelope.event_id)
        raise RuntimeError("handler boom")

    env = make_envelope("app.fail")
    await backend.publish(env)
    await backend.start_consumer(failing_consumer)
    await wait_until(lambda: len(calls) == 1)
    await asyncio.sleep(0.05)
    # No ACK → stays pending for reclaim; dedup key released for retry.
    assert fake_redis.acked == []
    pending = fake_redis.groups[("parrot:stream:app", "parrot-bus")]["pending"]
    assert "1-0" in pending
    assert f"parrot:events:dedup:{env.event_id}" not in fake_redis.kv
    await backend.close()


async def test_streams_poison_entry_acked_and_dropped(fake_redis):
    await fake_redis.xadd("parrot:stream:app", {"envelope": "not-json{{{"})
    backend = make_backend(fake_redis)
    received: list[EventEnvelope] = []

    async def consumer(envelope):
        received.append(envelope)

    await backend.start_consumer(consumer)
    await wait_until(lambda: len(fake_redis.acked) == 1)  # poison ACKed away
    assert received == []
    await backend.close()


# ---------------------------------------------------------------------------
# Integration (real Redis) — spec §4 test_end_to_end_streams_mode
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_end_to_end_streams_two_consumers():
    """Two consumers in one group: at-least-once, no double-processing."""
    import redis.asyncio as aioredis

    redis_url = os.environ.get("REDIS_TEST_URL", "redis://localhost:6379/9")
    try:
        probe = await aioredis.from_url(redis_url)
        await probe.ping()
        await probe.flushdb()
        await probe.close()
    except Exception:
        pytest.skip(f"No Redis reachable at {redis_url}")

    received_a: list[str] = []
    received_b: list[str] = []

    backend_a = RedisStreamsBackend(
        redis_url, consumer_name="itest-a", block_ms=100,
        autoclaim_interval=999, stream_refresh_interval=0.1,
    )
    backend_b = RedisStreamsBackend(
        redis_url, consumer_name="itest-b", block_ms=100,
        autoclaim_interval=999, stream_refresh_interval=0.1,
    )

    async def consumer_a(env):
        received_a.append(env.event_id)

    async def consumer_b(env):
        received_b.append(env.event_id)

    envs = [make_envelope(f"itest.job{i}") for i in range(20)]
    for env in envs:
        await backend_a.publish(env)

    await backend_a.start_consumer(consumer_a)
    await backend_b.start_consumer(consumer_b)
    await wait_until(
        lambda: len(received_a) + len(received_b) == 20, timeout=10.0
    )
    await asyncio.sleep(0.3)

    processed = received_a + received_b
    assert sorted(processed) == sorted(e.event_id for e in envs)
    assert len(set(processed)) == 20  # each processed exactly once (dedup)
    await backend_a.close()
    await backend_b.close()
