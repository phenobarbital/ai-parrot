"""Studio Test tab keeps conversation history across turns (real app, handlers, session, Postgres).

Only the LLM client is test-owned (``ScriptedClient``, replies with the number of history messages it received).
"""

from __future__ import annotations

import os

import pytest
from redis.asyncio import Redis
from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.bots.basic import BasicBot
from parrot.handlers.studio import agents as agents_module
from parrot.registry import registry as registry_module
from parrot.handlers.studio.conversation import KEY_PREFIX

from ._scripted_llm import PROVIDER, ScriptedClient, history_seen
from .test_testing_db_mode import BASE, KEY, _app, pool  # noqa: F401  (pool is a fixture)


REDIS_URL = os.environ.get("TEST_STUDIO_REDIS_URL", "")  # a DEDICATED db: the fixture deletes only its own prefix


@pytest.fixture
async def shared_redis(monkeypatch):
    """The Studio conversation backend switched to a real Redis; its own keys are removed afterwards."""
    if not REDIS_URL:
        pytest.skip("TEST_STUDIO_REDIS_URL not set; the redis conversation backend needs a Redis")
    monkeypatch.setenv("STUDIO_CONVERSATION_BACKEND", "redis")
    monkeypatch.setenv("STUDIO_CONVERSATION_REDIS_URL", REDIS_URL)
    monkeypatch.setenv("STUDIO_CONVERSATION_TTL_SECONDS", "600")
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    keys = [k async for k in client.scan_iter(match=f"{KEY_PREFIX}*")]
    if keys:
        await client.delete(*keys)
    await client.aclose()


@pytest.fixture
def scripted(monkeypatch, tmp_path):
    monkeypatch.setitem(SUPPORTED_CLIENTS, PROVIDER, ScriptedClient)
    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("STUDIO_SWEEP_INTERVAL_SECONDS", "3600")
    monkeypatch.setattr(agents_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path / "agents")


async def _client(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    resp = await client.post(
        f"{BASE}/agents", json={"name": "alpha", "bot_class": "BasicBot", "llm": f"{PROVIDER}:m"}
    )
    assert resp.status == 201, await resp.text()
    return client


async def _ask(client, query, user="u1", name="alpha"):
    resp = await client.post(f"{BASE}/agents/{name}/test/ask", json={"query": query}, headers={"X-User": user})
    body = await resp.json()
    assert resp.status == 200, body
    return history_seen(body["response"])


async def test_second_http_turn_sees_the_first(aiohttp_client, pool, scripted):
    client = await _client(aiohttp_client, pool)
    assert await _ask(client, "how many champions has real madrid") == 0
    assert await _ask(client, "i think they have 15 already") == 2  # user + assistant of turn 1


async def test_history_is_per_user(aiohttp_client, pool, scripted):
    client = await _client(aiohttp_client, pool)
    assert await _ask(client, "one", user="u1") == 0
    assert await _ask(client, "one", user="u2") == 0  # another caller never inherits u1's history


class _LegacyScripted(BasicBot):
    """A registry (non-Studio) agent on the scripted LLM: the legacy ``get_bot(new=True)`` test path."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("llm", f"{PROVIDER}:m")
        super().__init__(*args, **kwargs)


async def test_legacy_second_http_turn_sees_the_first(aiohttp_client, pool, scripted):
    client = await aiohttp_client(_app(pool))
    manager = client.app["bot_manager"]
    manager.registry.register("legacy-one", _LegacyScripted)
    manager._botdef["legacy-one"] = _LegacyScripted
    assert await _ask(client, "first", name="legacy-one") == 0
    assert await _ask(client, "second", name="legacy-one") == 2


async def _second_worker(client, user="u1"):
    """Drop the session's bot instance: what a turn landing on another worker / a swept instance looks like."""
    runtime = client.app["bot_manager"].studio
    sid = client.app["_sessions"][user]["studio_test:" + KEY.qualified]
    assert runtime._cache.session(KEY.qualified, sid) is not None
    runtime.evict_session(KEY, sid)
    assert runtime._cache.session(KEY.qualified, sid) is None
    return sid


async def test_default_backend_loses_history_when_the_instance_is_gone(aiohttp_client, pool, scripted):
    client = await _client(aiohttp_client, pool)
    assert await _ask(client, "one") == 0
    await _second_worker(client)
    assert await _ask(client, "two") == 0  # in-process memory: today's behaviour for a host that sets nothing


async def test_redis_backend_keeps_history_on_another_worker(aiohttp_client, pool, scripted, shared_redis):
    client = await _client(aiohttp_client, pool)
    assert await _ask(client, "one") == 0
    sid = await _second_worker(client)
    assert await _ask(client, "two") == 2  # a rebuilt instance reads the shared conversation
    keys = [k async for k in shared_redis.scan_iter(match=f"{KEY_PREFIX}*")]
    assert any(k.endswith(f":u1:{sid}") for k in keys), keys  # keyed (chatbot, user, session)
    ttls = [await shared_redis.ttl(k) for k in keys if k.endswith(f":u1:{sid}")]
    assert ttls and all(0 < t <= 600 for t in ttls)


async def test_redis_backend_keeps_users_apart(aiohttp_client, pool, scripted, shared_redis):
    client = await _client(aiohttp_client, pool)
    assert await _ask(client, "one", user="u1") == 0
    assert await _ask(client, "one", user="u2") == 0
    await _second_worker(client, "u1")
    assert await _ask(client, "two", user="u1") == 2
    assert await _ask(client, "two", user="u2") == 2


async def test_stop_clears_the_shared_conversation(aiohttp_client, pool, scripted, shared_redis):
    client = await _client(aiohttp_client, pool)
    assert await _ask(client, "one") == 0
    assert await _ask(client, "two") == 2
    assert [k async for k in shared_redis.scan_iter(match=f"{KEY_PREFIX}*")]
    assert (await client.delete(f"{BASE}/agents/alpha/test")).status == 200  # Stop
    assert not [k async for k in shared_redis.scan_iter(match=f"{KEY_PREFIX}:*")]
    assert await _ask(client, "three") == 0  # a new test session starts empty


async def test_stop_on_another_worker_still_clears(aiohttp_client, pool, scripted, shared_redis):
    client = await _client(aiohttp_client, pool)
    assert await _ask(client, "one") == 0
    await _second_worker(client)  # no live instance on the worker that handles Stop
    assert (await client.delete(f"{BASE}/agents/alpha/test")).status == 200
    assert not [k async for k in shared_redis.scan_iter(match=f"{KEY_PREFIX}:*")]
