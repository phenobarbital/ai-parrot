"""FEAT-622 Wave 4 end-to-end scope regressions (spec §4 integration rows, ARCHITECTURE R6.5).

The join is crossed for real: seam-shaped request → resolver → Studio test chat → the agent's own ``tool_manager`` inside
the handler's ``bot.session`` → a tenant-bound host toolkit that reads the scope the SERVER bound. No LLM is reached.
"""
from __future__ import annotations

import asyncio
import importlib

import pytest
from aiohttp.test_utils import make_mocked_request

from parrot.bots.abstract import AbstractBot
from parrot.bots.base import BaseBot
from parrot.bots.basic import BasicBot
from parrot.handlers.scope import RequestScope
from parrot.handlers.studio.access import StudioAgentRef, build_tool_scope

from ._host_probe import host_plugins  # noqa: F401
from .test_agents_db_mode import BASE, _offline, pool  # noqa: F401  (fixtures)
from .test_agents_visibility import create, tenant_app, who


def _probe():
    return importlib.import_module("plugins.tools.probe")


def _scope(user, tenant, agent=None):
    return build_tool_scope(RequestScope(user_id=user, tenant=tenant, groups=frozenset()), agent)


@pytest.fixture
def chat_calls(monkeypatch):
    """``ask`` runs the agent's own ``whoami`` tool through ``tool_manager.execute_tool`` (the LLM seam)."""
    results: list = []

    async def _ask(self, question=None, **_kw):
        if "tp_whoami" not in self.tool_manager.list_tools():       # the runtime's configure() is replaced offline
            self.tool_manager.register_toolkit(_probe().ProbeTenantToolkit())
        results.append(await self.tool_manager.execute_tool("tp_whoami", {}, return_tool_result=True))
        return type("R", (), {"content": "ok", "metadata": {}})()

    monkeypatch.setattr(BasicBot, "ask", _ask)
    monkeypatch.setattr(BaseBot, "ask", _ask)
    return results


async def test_test_chat_join_scope_reaches_tool(aiohttp_client, pool, host_plugins, chat_calls):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    assert (await create(client, "alpha", who("u1", groups="g1"), visibility="tenant"))[0].status == 201
    resp = await client.post(f"{BASE}/agents/alpha/test/ask", json={"query": "hi"}, headers=who("u2", groups="g2"))
    assert resp.status == 200, await resp.text()
    result = chat_calls[-1]
    assert result.status == "success", result
    seen = result.result
    assert seen["tenant"] == "acme" and seen["user_id"] == "u2"                      # the CALLER's tenant and id
    assert seen["agent"] == {"name": "alpha", "owner": "u1", "tenant": "acme", "visibility": "tenant"}


def _shared_agent():
    """One agent instance shared by every caller, with the tenant-bound toolkit registered."""
    probe = _probe()
    bot = BasicBot(name="shared")
    bot.tool_manager.register_toolkit(probe.ProbeTenantToolkit())
    return bot


async def _call_inside_session(bot, scope, gate):
    request = make_mocked_request("POST", "/x")
    async with bot.session(request=request, app={}, studio_scope=scope):
        await gate.wait()                       # every caller is inside its session before any tool runs
        await asyncio.sleep(0)
        return await bot.tool_manager.execute_tool("tp_whoami", {}, return_tool_result=True)


async def test_concurrent_callers_never_cross(host_plugins, monkeypatch):  # noqa: F811
    monkeypatch.setattr(AbstractBot, "configure", lambda *a, **k: None, raising=False)
    bot = _shared_agent()
    gate = asyncio.Event()
    scopes = [_scope(f"user{i}", f"tenant{i % 2}", StudioAgentRef(None, "shared", "o", f"tenant{i % 2}", "tenant"))
              for i in range(6)]
    tasks = [asyncio.create_task(_call_inside_session(bot, scope, gate)) for scope in scopes]
    await asyncio.sleep(0.05)
    gate.set()
    results = await asyncio.gather(*tasks)
    for index, result in enumerate(results):
        assert result.status == "success", result
        assert result.result["user_id"] == f"user{index}" and result.result["tenant"] == f"tenant{index % 2}"


async def test_tenant_mismatch_refuses(host_plugins, monkeypatch):  # noqa: F811
    bot = _shared_agent()
    counters = _probe().COUNTERS
    counters["executed"] = 0
    foreign_agent = StudioAgentRef(None, "shared", "o", "tenant-A", "tenant")
    request = make_mocked_request("POST", "/x")
    async with bot.session(request=request, app={}, studio_scope=_scope("u1", "tenant-B", foreign_agent)):
        result = await bot.tool_manager.execute_tool("tp_whoami", {}, return_tool_result=True)
    assert result.status == "error" and result.metadata["error_code"] == "tool_scope_unavailable"
    assert result.metadata["reason"] == "tenant_mismatch" and counters["executed"] == 0


async def test_no_request_refuses(host_plugins):  # noqa: F811
    """The scheduler shape: a tool called outside any ``bot.session`` has no context at all."""
    bot = _shared_agent()
    counters = _probe().COUNTERS
    counters["executed"] = 0
    result = await bot.tool_manager.execute_tool("tp_whoami", {}, return_tool_result=True)
    assert result.status == "error" and result.metadata["error_code"] == "tool_scope_unavailable"
    assert result.metadata["reason"] == "no_context" and counters["executed"] == 0
