"""FEAT-605 W3.6 — the assistant is partitioned by (tenant, user): session, instance, toolset and memory identity."""
from __future__ import annotations

import asyncio
from collections import Counter
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from navigator_session.data import SessionData

from parrot.bots.studio import AgentStudioAgent
from parrot.handlers.studio import meta_agent, setup_studio_routes
from parrot.manager.manager import BotManager

from .test_agents_db_mode import BASE, _offline, pool  # noqa: F401  (fixtures)
from .test_agents_visibility import HeaderResolver, who


def _key(tenant, user_id) -> str:
    return meta_agent.Partition(tenant, user_id).key


def partition_app(pool, *, resolver: bool = True) -> web.Application:  # noqa: F811
    """Like ``tenant_app`` but ONE persistent ``SessionData`` per user (a login that switches tenants)."""
    sessions: dict[str, SessionData] = {}

    @web.middleware
    async def _session(request, handler):
        user = request.headers.get("X-User", "u1")
        request["NAV_SESSION"] = sessions.setdefault(
            user, SessionData(data={"session": {"user_id": user, "groups": [], "superuser": False}}))
        request["authenticated"] = True
        return await handler(request)

    app = web.Application(middlewares=[_session])
    app["database"] = pool
    if resolver:
        app["scope_resolver"] = HeaderResolver()
    BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True,
               enable_swagger_api=False).setup_registry_only(app)
    setup_studio_routes(app)
    app["_sessions"] = sessions
    return app


@pytest.fixture
def probe(monkeypatch):
    """Offline assistant instances; every ask and every cleanup is recorded."""
    from parrot.clients.anthropic import AnthropicClient

    log = {"asks": [], "cleanups": Counter(), "built": []}

    def _factory(**kwargs):
        agent = AgentStudioAgent(llm=MagicMock(spec=AnthropicClient), **kwargs)
        log["built"].append(agent)
        return agent

    async def _ask(self, question=None, **kw):
        log["asks"].append({"name": self.name, "memory_key": self.memory_key_id, **kw})
        return type("R", (), {"content": "ok", "metadata": {}})()

    async def _cleanup(self):
        log["cleanups"][self.name] += 1

    monkeypatch.setattr(meta_agent, "AgentStudioAgent", _factory)
    monkeypatch.setattr(AgentStudioAgent, "ask", _ask)
    monkeypatch.setattr(AgentStudioAgent, "cleanup", _cleanup)
    return log


async def say(client, caller, text="hi"):
    return await client.post(f"{BASE}/assistant", json={"query": text, "use_byok": False}, headers=caller)


async def test_alternating_tenants_never_cross_history(aiohttp_client, pool, probe):  # noqa: F811
    client = await aiohttp_client(partition_app(pool))
    acme, globex = who("u1", "acme"), who("u1", "globex")        # the SAME login (one session) switching tenants
    for caller in (acme, globex, acme, globex):
        assert (await say(client, caller)).status == 200
    a1, b1, a2, b2 = probe["asks"]
    assert a1["name"] == a2["name"] and b1["name"] == b2["name"] and a1["name"] != b1["name"]   # reused per partition
    assert a1["memory_key"] == "agent_studio:acme" and b1["memory_key"] == "agent_studio:globex"
    assert a1["session_id"] == a2["session_id"] and b1["session_id"] == b2["session_id"]
    assert a1["session_id"] != b1["session_id"]                                                  # one conversation each
    assert {a1["user_id"], b1["user_id"]} == {"u1"}                                              # explicit, never "anonymous"
    assert len(probe["built"]) == 2


async def test_toolset_and_instances_are_not_shared(aiohttp_client, pool, probe):  # noqa: F811
    client = await aiohttp_client(partition_app(pool))
    for caller in (who("u1", "acme"), who("u1", "globex"), who("u2", "acme")):
        assert (await say(client, caller)).status == 200
    a, b, c = probe["built"]
    assert len({id(a), id(b), id(c)}) == 3
    assert len({id(a.tool_manager), id(b.tool_manager), id(c.tool_manager)}) == 3
    assert probe["asks"][2]["user_id"] == "u2" and probe["asks"][2]["name"] == c.name   # another user, same tenant


async def test_delete_resets_only_the_partition(aiohttp_client, pool, probe):  # noqa: F811
    app = partition_app(pool)
    client = await aiohttp_client(app)
    acme, globex = who("u1", "acme"), who("u1", "globex")
    await say(client, acme)
    await say(client, globex)
    session = app["_sessions"]["u1"]["session"] if False else app["_sessions"]["u1"]
    assert set(session.get(meta_agent.SESSION_KEY)) == {_key("acme", "u1"), _key("globex", "u1")}
    resp = await client.delete(f"{BASE}/assistant", headers=acme)
    assert resp.status == 200
    assert set(session.get(meta_agent.SESSION_KEY)) == {_key("globex", "u1")}                  # the other partition untouched
    assert sum(probe["cleanups"].values()) == 1                                       # that instance cleaned once
    acme_instance, globex_instance = probe["built"]
    assert probe["cleanups"] == Counter({acme_instance.name: 1})
    await say(client, globex)                                                         # globex continues, same instance
    assert probe["asks"][-1]["name"] == globex_instance.name and len(probe["built"]) == 2
    await say(client, acme)                                                           # acme starts a NEW conversation
    assert len(probe["built"]) == 3 and probe["asks"][-1]["name"] != acme_instance.name
    assert (await client.delete(f"{BASE}/assistant", headers=globex)).status == 200
    assert (await client.delete(f"{BASE}/assistant", headers=who("u1", "acme"))).status == 200
    assert meta_agent.SESSION_KEY not in session                                      # last partition gone: key gone


async def test_tampered_session_misses(aiohttp_client, pool, probe):  # noqa: F811
    app = partition_app(pool)
    client = await aiohttp_client(app)
    await say(client, who("u1", "globex"))
    globex_instance = probe["built"][0]
    session = app["_sessions"]["u1"]
    # the acme partition's entry is forged to name globex's instance: the lookup is a miss, a NEW instance is built
    session[meta_agent.SESSION_KEY] = {**session[meta_agent.SESSION_KEY],
                                       _key("acme", "u1"): {"instance": globex_instance.name, "session_id": "forged"}}
    assert (await say(client, who("u1", "acme"))).status == 200
    assert len(probe["built"]) == 2 and probe["asks"][-1]["name"] != globex_instance.name
    assert probe["asks"][-1]["memory_key"] == "agent_studio:acme"
    # a legacy / garbage entry shape is ignored, not trusted
    session[meta_agent.SESSION_KEY] = globex_instance.name
    assert (await say(client, who("u1", "acme"))).status == 200
    assert len(probe["built"]) == 3
    # the cache itself refuses an instance recorded for another partition
    instances = app[meta_agent._ASSISTANTS_APP_KEY]
    stolen = next(a for a in probe["built"] if a._assistant_partition == ("globex", "u1"))
    instances[("acme", "u1", stolen.name)] = stolen
    session[meta_agent.SESSION_KEY] = {_key("acme", "u1"): {"instance": stolen.name, "session_id": "s"}}
    assert (await say(client, who("u1", "acme"))).status == 200
    assert probe["asks"][-1]["name"] != stolen.name


async def test_tenant_required_before_any_instance(aiohttp_client, pool, probe):  # noqa: F811
    app = partition_app(pool)
    client = await aiohttp_client(app)
    for method in ("post", "delete"):
        kwargs = {"json": {"query": "hi"}} if method == "post" else {}
        resp = await getattr(client, method)(f"{BASE}/assistant", headers=who("u1", None), **kwargs)
        assert resp.status == 422 and (await resp.json())["code"] == "tenant_required"
    assert probe["built"] == [] and not app.get(meta_agent._ASSISTANTS_APP_KEY)


async def test_plain_host_partition_is_the_user(aiohttp_client, pool, probe):  # noqa: F811
    app = partition_app(pool, resolver=False)
    client = await aiohttp_client(app)
    assert (await say(client, {"X-User": "u1"})).status == 200
    assert probe["asks"][0]["memory_key"] == "agent_studio:-" and probe["asks"][0]["user_id"] == "u1"
    assert set(app["_sessions"]["u1"][meta_agent.SESSION_KEY]) == {_key(None, "u1")}


async def test_app_cleanup_cleans_every_instance_once(aiohttp_client, pool, probe):  # noqa: F811
    app = partition_app(pool)
    client = await aiohttp_client(app)
    for caller in (who("u1", "acme"), who("u1", "globex"), who("u2", "acme")):
        await say(client, caller)
    await meta_agent.cleanup_studio_assistants(app)
    assert probe["cleanups"] == Counter({a.name: 1 for a in probe["built"]})
    await meta_agent.cleanup_studio_assistants(app)                                  # idempotent: nothing left to clean
    assert sum(probe["cleanups"].values()) == 3


def test_cleanup_hook_installed_once_per_app(pool):  # noqa: F811
    app = web.Application()
    setup_studio_routes(app)
    setup_studio_routes(app, prefix="/api/v1/{tenant}/astudio")      # a second mount: still one hook
    assert app.on_cleanup.count(meta_agent.cleanup_studio_assistants) == 1


def test_partition_is_a_tuple_without_collisions():
    """Tenant ``-`` vs no tenant, and ``:`` inside ids, never produce the same partition or session key."""
    P = meta_agent.Partition
    pairs = [P(None, "u1"), P("-", "u1"), P("a:b", "c"), P("a", "b:c"), P("a", "b"), P("a:b", "")]
    assert len({tuple(p) for p in pairs}) == len(pairs) and len({p.key for p in pairs}) == len(pairs)
    assert P(None, "u1").chatbot_id == "agent_studio:-" == P("-", "u1").chatbot_id    # the memory id keeps the spec shape


async def test_delete_defers_cleanup_while_an_ask_is_in_flight(aiohttp_client, pool, probe, monkeypatch):  # noqa: F811
    app = partition_app(pool)
    client = await aiohttp_client(app)
    started, release = asyncio.Event(), asyncio.Event()

    async def _slow_ask(self, question=None, **kw):
        started.set()
        await release.wait()
        return type("R", (), {"content": "late", "metadata": {}})()

    monkeypatch.setattr(AgentStudioAgent, "ask", _slow_ask)
    caller = who("u1", "acme")
    pending = asyncio.create_task(say(client, caller))
    await asyncio.wait_for(started.wait(), 5)
    agent = probe["built"][0]
    resp = await client.delete(f"{BASE}/assistant", headers=caller)
    assert resp.status == 200
    assert probe["cleanups"][agent.name] == 0                      # the in-flight ask still uses it
    release.set()
    answer = await pending
    assert answer.status == 200 and (await answer.json())["response"] == "late"
    assert probe["cleanups"] == Counter({agent.name: 1})            # cleaned once, after the ask finished
    # a DELETE with no ask in flight still cleans immediately, exactly once
    await say(client, caller)
    fresh = probe["built"][1]
    await client.delete(f"{BASE}/assistant", headers=caller)
    assert probe["cleanups"][fresh.name] == 1


async def test_an_instance_is_cleaned_at_most_once(probe):
    class Agent:
        name = "x"

        async def cleanup(self):
            probe["cleanups"]["x"] += 1

    agent = Agent()
    await meta_agent._retire(agent)
    await meta_agent._retire(agent)
    await meta_agent._cleanup_once(agent)
    assert probe["cleanups"]["x"] == 1
