"""FEAT-622 M5: every entry point binds ``studio_scope`` (chat, direct execute, options, test chat)."""
from __future__ import annotations

import importlib
import uuid
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.bots.abstract import AbstractBot
from parrot.bots.basic import BasicBot
from parrot.handlers.chat import ChatHandler
from parrot.handlers.scope import RequestScope
from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio import toolkit_config as tc
from parrot.handlers.studio.storage.models import StudioAgentKey
from parrot.manager.manager import BotManager
from parrot.tools.scope import ToolScopeUnavailable, require_tool_scope
from parrot.utils.helpers import current_context

from ._host_probe import host_plugins  # noqa: F401
from .test_agents_db_mode import _session
from .test_scope_enforcement_handlers import BASE
from .test_toolkit_config import _handler, _state, _store, _unwrap


class Resolver:
    """A real scope resolver. ``tenant=None`` models a caller with no tenant."""

    def __init__(self, tenant="acme"):
        self.tenant = tenant

    async def resolve(self, request):
        return RequestScope(user_id="u1", tenant=self.tenant, groups=frozenset({"g1"}))


def _app(*, resolver=None) -> web.Application:
    app = web.Application(middlewares=[_session])
    if resolver is not None:
        app["scope_resolver"] = resolver
    manager = BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True,
                         enable_swagger_api=False)
    manager.setup_registry_only(app)
    setup_studio_routes(app)
    app.router.add_view("/api/v1/chat/{chatbot_name}", ChatHandler)
    return app


@pytest.fixture
def seen(monkeypatch):
    """Offline bot: ``ask`` / ``ask_stream`` record the studio_scope bound at that moment (and what the gate says)."""
    log: list = []

    def _record(kind):
        ctx = current_context()
        scope = None if ctx is None else ctx.kwargs.get("studio_scope")
        try:
            require_tool_scope(tool_name="probe")
            gate = "ok"
        except ToolScopeUnavailable as exc:
            gate = exc.reason
        log.append({"kind": kind, "scope": scope, "gate": gate})

    async def _ask(self, question=None, **_kw):
        _record("ask")
        return {"answer": "ok"}

    async def _ask_stream(self, **_kw):
        async def gen():
            _record("stream")        # consumed by the handler, inside the ``async with chatbot.session`` block
            yield {"event": "done"}

        return gen()

    monkeypatch.setattr(AbstractBot, "configure", AsyncMock())
    monkeypatch.setattr(BasicBot, "ask", _ask)
    monkeypatch.setattr(BasicBot, "ask_stream", _ask_stream)
    return log


async def _chat_client(aiohttp_client, *, resolver, bot_attrs=None):
    app = _app(resolver=resolver)
    bot = BasicBot(name="chat-bot")
    app["bot_manager"].add_bot(bot)
    for key, value in (bot_attrs or {}).items():   # the Studio stamps come after: BotManager refuses a Studio instance
        setattr(bot, key, value)
    return await aiohttp_client(app)


async def _chat(client, **body):
    resp = await client.post("/api/v1/chat/chat-bot", json={"query": "hi", **body}, headers={"X-User": "u1"})
    return resp


async def test_normal_chat_binds_scope(aiohttp_client, seen):
    client = await _chat_client(aiohttp_client, resolver=Resolver())
    resp = await _chat(client)
    assert resp.status == 200, await resp.text()
    entry = seen[-1]
    assert entry["scope"].caller.tenant == "acme" and entry["scope"].caller.user_id == "u1"
    assert entry["scope"].agent is None and entry["gate"] == "ok"        # a non-Studio bot binds agent=None


async def test_normal_chat_binds_the_studio_agent_ref(aiohttp_client, seen):
    attrs = {"_studio_key": StudioAgentKey(None, "chat-bot"), "_studio_agent_id": uuid.uuid4(), "_tooling_owner": "u1"}
    client = await _chat_client(aiohttp_client, resolver=Resolver(), bot_attrs=attrs)
    assert (await _chat(client)).status == 200
    agent = seen[-1]["scope"].agent
    assert agent.name == "chat-bot" and agent.tenant is None and agent.owner == "u1"
    assert seen[-1]["gate"] == "agent_tenant_unset"                       # v1: tenant-NULL Studio rows refuse in tools


async def test_chat_without_a_resolver_binds_nothing(aiohttp_client, seen):
    client = await _chat_client(aiohttp_client, resolver=None)
    assert (await _chat(client)).status == 200
    assert seen[-1]["scope"] is None and seen[-1]["gate"] == "no_scope"


async def test_streaming_chat_keeps_the_context(aiohttp_client, seen):
    client = await _chat_client(aiohttp_client, resolver=Resolver())
    resp = await _chat(client, stream=True)
    assert resp.status == 200
    await resp.read()
    entry = seen[-1]
    assert entry["kind"] == "stream" and entry["scope"].caller.tenant == "acme" and entry["gate"] == "ok"


async def _execute(client, slug):
    resp = await client.post(f"{BASE}/tools/{slug}/execute", json={"args": {"value": "x"}})
    return resp, await resp.json()


async def test_execute_binds_caller_scope_agent_none(aiohttp_client, host_plugins):  # noqa: F811
    client = await aiohttp_client(_app(resolver=Resolver()))
    resp, body = await _execute(client, "tp_tenant_tool")
    assert resp.status == 200, body                                        # the caller's scope is bound: it runs
    counters = importlib.import_module("plugins.tools.probe").COUNTERS
    assert counters["constructed"] == 1 and counters["executed"] == 1


async def test_execute_refuses_without_a_resolver_and_without_a_tenant(aiohttp_client, host_plugins):  # noqa: F811
    plain = await aiohttp_client(_app(resolver=None))
    resp, body = await _execute(plain, "tp_tenant_tool")
    assert resp.status == 403 and body["details"] == {"reason": "no_scope"}
    tenantless = await aiohttp_client(_app(resolver=Resolver(tenant=None)))
    resp, body = await _execute(tenantless, "tp_tenant_tool")
    assert resp.status == 422 and body["code"] == "tenant_required"
    counters = importlib.import_module("plugins.tools.probe").COUNTERS
    assert counters["constructed"] == 0 and counters["executed"] == 0


async def test_execute_refuses_mismatched_scope(aiohttp_client, host_plugins):  # noqa: F811
    """The host tool's own tenant check raises ``host_tenant_mismatch``: the structured refusal is a 403, not a 200."""
    client = await aiohttp_client(_app(resolver=Resolver()))
    resp, body = await _execute(client, "tp_tenant_mismatch_tool")
    assert resp.status == 403 and body["code"] == "tool_scope_unavailable"
    assert body["details"] == {"reason": "host_tenant_mismatch"}


async def test_options_bind_the_scope(host_plugins, monkeypatch):  # noqa: F811
    probe = importlib.import_module("plugins.tools.probe")
    _store(monkeypatch, _state(), schema_for=lambda slug: (probe.ProbeTenantToolkit, {}))
    monkeypatch.setattr(tc, "hydrate_params", AsyncMock(return_value={}))
    from parrot.tools.spec import ToolkitSpec

    state = _state(toolkits=[ToolkitSpec(slug="tp_tenant", params={})])
    _store(monkeypatch, state, schema_for=lambda slug: (probe.ProbeTenantToolkit, {}))
    for resolver, expected in ((Resolver(), 200), (None, 403)):
        handler = _handler(tc.StudioToolkitOptionsHandler, "GET", {"name": "agent", "slug": "tp_tenant", "param": "project"})
        if resolver is not None:
            handler.request.app["scope_resolver"] = resolver
        response = await _unwrap(tc.StudioToolkitOptionsHandler.get)(handler)
        assert response.status == expected
    # the context never leaks out of the handler
    assert current_context() is None
    assert make_mocked_request("GET", "/x") is not None
