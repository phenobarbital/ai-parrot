"""FEAT-621 W3 test chat in database mode (AC9, AC14, spec §2.7/§2.7a/§2.8).

Real aiohttp app, real Studio routes, a session middleware that keeps ONE real ``SessionData`` per user across
requests (the test-session id lives in it) and a real Postgres pool. ``AbstractBot.configure`` and ``BasicBot.ask``
are replaced so no LLM is ever reached.
"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from asyncdb import AsyncPool
from navigator_session.data import SessionData

from parrot.bots.abstract import AbstractBot
from parrot.bots.agent import Agent
from parrot.bots.base import BaseBot
from parrot.bots.basic import BasicBot
from parrot.handlers.studio import agents as agents_module
from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio.storage.migrate import apply_studio_migrations
from parrot.handlers.studio.storage.models import StudioAgentKey, StudioPartition
from parrot.handlers.studio.testing import StudioTestingHandler
from parrot.manager.manager import BotManager
from parrot.registry import registry as registry_module

BASE = "/api/v1/astudio"
TABLES = ("ai_agent_assets", "ai_agent_tooling", "ai_agent_drafts", "ai_agents", "ai_skills_catalog")
KEY = StudioAgentKey(None, "alpha")


@pytest.fixture
async def pool():
    dsn = os.environ.get("TEST_STUDIO_PG_DSN")
    if not dsn:
        pytest.skip("TEST_STUDIO_PG_DSN not set; Studio handler integration tests need Postgres")
    pg = AsyncPool("pg", dsn=dsn)
    await pg.connect()
    await apply_studio_migrations(pg)
    async with pg.acquire() as conn:
        for table in TABLES:
            await conn.execute(f"TRUNCATE navigator.{table} CASCADE")
    yield pg
    async with pg.acquire() as conn:
        for table in TABLES:
            await conn.execute(f"TRUNCATE navigator.{table} CASCADE")
    await pg.close()


@pytest.fixture
def asks(monkeypatch, tmp_path):
    """Offline bots; every ``ask`` is recorded as ``(bot, leases held at that moment)``."""
    log: list = []
    monkeypatch.setattr(AbstractBot, "configure", AsyncMock())
    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("STUDIO_SWEEP_INTERVAL_SECONDS", "3600")
    monkeypatch.setattr(agents_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path / "agents")

    async def _ask(self, question=None, **_kw):
        entries = [e for e in _RUNTIME[0]._cache.all_entries() if e.bot is self] if _RUNTIME else []
        log.append((self, [e.leases for e in entries]))
        return SimpleNamespace(content=f"echo:{question}", metadata={"bot": self.name})

    monkeypatch.setattr(BasicBot, "ask", _ask)
    monkeypatch.setattr(Agent, "ask", _ask)
    monkeypatch.setattr(BaseBot, "ask", _ask)
    _RUNTIME.clear()
    return log


_RUNTIME: list = []


def _app(pool) -> web.Application:
    sessions: dict[str, SessionData] = {}

    @web.middleware
    async def _session(request, handler):
        user = request.headers.get("X-User", "u1")
        request["NAV_SESSION"] = sessions.setdefault(
            user, SessionData(data={"session": {"user_id": user, "groups": [], "superuser": False}})
        )
        request["authenticated"] = True
        return await handler(request)

    app = web.Application(middlewares=[_session])
    app["database"] = pool
    manager = BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True,
                         enable_swagger_api=False)
    manager.setup_registry_only(app)
    setup_studio_routes(app)
    app["_sessions"] = sessions
    return app


async def _client(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    _RUNTIME[:] = [client.app["bot_manager"].studio]
    return client


async def _create(client, name="alpha"):
    resp = await client.post(f"{BASE}/agents", json={"name": name, "bot_class": "BasicBot"})
    assert resp.status == 201
    return await resp.json()


async def _ask(client, name="alpha", query="hi", user="u1"):
    return await client.post(f"{BASE}/agents/{name}/test/ask", json={"query": query}, headers={"X-User": user})


async def test_studio_test_chat_uses_runtime_cache(aiohttp_client, pool, asks):
    client = await _client(aiohttp_client, pool)
    await _create(client)
    manager, runtime = client.app["bot_manager"], client.app["bot_manager"].studio
    resp = await _ask(client)
    body = await resp.json()
    assert resp.status == 200 and body["response"] == "echo:hi" and body["agent_name"] == "alpha"
    assert (await _ask(client, query="again")).status == 200
    assert len(asks) == 2 and asks[0][0] is asks[1][0]                  # the session instance is reused
    sid = client.app["_sessions"]["u1"]["studio_test:" + KEY.qualified]
    entry = runtime._cache.session(KEY.qualified, sid)
    assert entry is not None and entry.bot is asks[0][0]
    assert not manager._bots and runtime._cache.current(KEY.qualified) is None   # nothing leaked to _bots/base


async def test_stale_version_fresh_build(aiohttp_client, pool, asks):
    client = await _client(aiohttp_client, pool)
    await _create(client)
    assert (await _ask(client)).status == 200
    resp = await client.patch(f"{BASE}/agents/alpha", json={"description": "v2"})
    assert resp.status == 200 and (await resp.json())["version"] == 2
    assert (await _ask(client)).status == 200
    assert asks[0][0] is not asks[1][0]                                  # rebuilt for the new version
    sid = client.app["_sessions"]["u1"]["studio_test:" + KEY.qualified]
    entry = client.app["bot_manager"].studio._cache.session(KEY.qualified, sid)
    assert entry.version == 2 and entry.bot is asks[1][0]


async def test_lease_held_during_ask(aiohttp_client, pool, asks):
    client = await _client(aiohttp_client, pool)
    await _create(client)
    assert (await _ask(client)).status == 200
    assert asks[0][1] == [1]                                             # leased while the ask ran
    sid = client.app["_sessions"]["u1"]["studio_test:" + KEY.qualified]
    entry = client.app["bot_manager"].studio._cache.session(KEY.qualified, sid)
    assert entry.leases == 0                                             # released afterwards


async def test_end_session_evicts(aiohttp_client, pool, asks):
    client = await _client(aiohttp_client, pool)
    await _create(client)
    await _ask(client)
    runtime, sessions = client.app["bot_manager"].studio, client.app["_sessions"]
    skey = "studio_test:" + KEY.qualified
    sid = sessions["u1"][skey]
    resp = await client.delete(f"{BASE}/agents/alpha/test")
    assert resp.status == 200 and (await resp.json())["message"] == "Test session for 'alpha' stopped"
    assert skey not in sessions["u1"] and runtime._cache.session(KEY.qualified, sid) is None
    resp = await client.delete(f"{BASE}/agents/alpha/test")
    assert resp.status == 200 and "No active test session" in (await resp.json())["message"]
    await _ask(client)
    assert asks[0][0] is not asks[1][0]                                  # a fresh session instance
    assert await runtime.sweep(now=time.monotonic() + 10_000) >= 1       # the retired entry is cleaned


class _AcmeTesting(StudioTestingHandler):
    """A tenant host stand-in: the partition is the ``acme`` tenant."""

    async def _studio_partition(self):
        return StudioPartition("acme")


async def test_tenant_partition_never_serves_global_rows(aiohttp_client, pool, asks):
    app = _app(pool)
    app.router.add_view("/tenant/agents/{name}/test/ask", _AcmeTesting)
    client = await aiohttp_client(app)
    _RUNTIME[:] = [app["bot_manager"].studio]
    await _create(client)                                                # a GLOBAL row
    resp = await client.post("/tenant/agents/alpha/test/ask", json={"query": "hi"})
    assert resp.status == 404 and (await resp.json())["code"] == "not_found"
    assert asks == [] and app["bot_manager"].studio._cache.all_entries() == []


class _LegacyBot(BasicBot):
    """A registry (non-Studio) agent."""

    async def ask(self, question=None, **_kw):
        return SimpleNamespace(content=f"echo:{question}", metadata={})


async def test_legacy_agent_test_chat_unchanged(aiohttp_client, pool, asks):
    client = await _client(aiohttp_client, pool)
    client.app["bot_manager"].registry.register("legacy-one", _LegacyBot)
    resp = await _ask(client, name="legacy-one")
    body = await resp.json()
    assert resp.status == 200 and body["response"] == "echo:hi"
    manager = client.app["bot_manager"]
    assert manager.studio._cache.all_entries() == []                     # the Studio cache was not involved
    assert any(name for name in manager._bots)                           # legacy keeps get_bot(new=True) -> _bots
    assert (await client.delete(f"{BASE}/agents/legacy-one/test")).status == 200
    assert not manager._bots
