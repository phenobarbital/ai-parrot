"""Studio Test tab keeps conversation history across turns (real app, handlers, session, Postgres).

Only the LLM client is test-owned (``ScriptedClient``, replies with the number of history messages it received).
"""

from __future__ import annotations

import pytest
from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.bots.basic import BasicBot
from parrot.handlers.studio import agents as agents_module
from parrot.registry import registry as registry_module

from ._scripted_llm import PROVIDER, ScriptedClient, history_seen
from .test_testing_db_mode import BASE, KEY, _app, pool  # noqa: F401  (pool is a fixture)


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
