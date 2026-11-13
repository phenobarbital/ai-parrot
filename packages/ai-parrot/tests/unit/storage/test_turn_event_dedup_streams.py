"""FEAT-886 — the bus dedup key has the storage key's scope (real Redis Streams via a throw-away redis-server)."""
from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import time

import pytest
from navigator_eventbus import EventBus, EventEnvelope
from navigator_eventbus.backends.redis_streams import RedisStreamsBackend

from parrot.memory.persistence import TURN_COMPLETED_TOPIC, turn_event_id


@pytest.fixture(scope="module")
def redis_url(tmp_path_factory):
    binary = shutil.which("redis-server")
    if not binary:
        pytest.skip("redis-server not installed")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([binary, "--port", str(port), "--save", "", "--appendonly", "no",
                             "--dir", str(tmp_path_factory.mktemp("redis"))],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.skip("redis-server did not start")
    yield f"redis://127.0.0.1:{port}/0"
    proc.terminate()
    proc.wait(timeout=5)


def _backend(url: str, prefix: str) -> RedisStreamsBackend:
    return RedisStreamsBackend(url, stream_prefix=prefix, dedup_prefix=f"{prefix}dedup:", group="parrot-turns")


async def _deliveries(url, envelopes, prefix):
    seen = []
    consumer = EventBus(backend=_backend(url, prefix))

    async def handler(env):
        seen.append(env.payload["n"])

    consumer.core.subscribe(TURN_COMPLETED_TOPIC, handler)
    await consumer.connect()
    producer = EventBus(backend=_backend(url, prefix), publish_only=True)
    await producer.connect()
    try:
        await asyncio.sleep(0.3)
        for env in envelopes:
            await producer.core.publish(env)
        await asyncio.sleep(1.5)
    finally:
        await producer.close()
        await consumer.close()
    return seen


def _env(n, agent="agent-a", user="u1", session="s1", turn="msg-1"):
    return EventEnvelope(topic=TURN_COMPLETED_TOPIC, payload={"n": n},
                         event_id=turn_event_id(agent, user, session, turn))


async def test_a_retry_of_the_same_turn_is_deduplicated(redis_url):
    seen = await _deliveries(redis_url, [_env(1), _env(2)], "t:retry:")  # same scope + same turn id
    assert seen == [1]


async def test_two_conversations_reusing_a_client_turn_id_are_both_delivered(redis_url):
    seen = await _deliveries(redis_url, [_env(1, user="u1"), _env(2, user="u2"), _env(3, session="s2"),
                                         _env(4, agent="agent-b")], "t:scope:")
    assert sorted(seen) == [1, 2, 3, 4]
