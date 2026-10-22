"""PA-10: host TOOL_CALL guardrails on every Studio-built bot (and the direct execute route).

Real app, real runtime build, real ``ToolManager.execute_tool`` pipeline; the guardrails are host code (test-owned
``Guardrail`` subclasses); only the LLM client is test-owned (scripted).
"""
from __future__ import annotations

import pytest

from parrot.bots.guardrails.base import Guardrail, GuardrailAction, GuardrailResult, GuardrailStage
from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.handlers import tools_catalog as tools_catalog_module
from parrot.handlers.studio import STUDIO_TOOL_CALL_GUARDRAILS, agents as agents_module
from parrot.handlers.studio import catalog as catalog_module
from parrot.registry import registry as registry_module
from parrot.tools.host_hooks import FEATURES
from parrot.tools.tooling_policy import TenantToolingPolicy, set_tenant_tooling_policy

from ._scripted_llm import PROVIDER, ScriptedClient
from .test_agents_db_mode import BASE, pool  # noqa: F401  (fixture)
from .test_agents_visibility import create, tenant_app, who

TOOL = "CalculatorTool"
BAD = {"operation": "evaluate", "expression": "http://127.0.0.1/"}
GOOD = {"operation": "add", "x": 1.0, "y": 2.0}


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setitem(SUPPORTED_CLIENTS, PROVIDER, ScriptedClient)
    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("STUDIO_SWEEP_INTERVAL_SECONDS", "3600")
    monkeypatch.setattr(agents_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(catalog_module, "_BASE_CLASSES_CACHE", None)
    monkeypatch.setattr(tools_catalog_module, "_CATALOG_CACHE", None)


class UrlGuard(Guardrail):
    """Blocks a call whose arguments mention a loopback address; records every context it sees."""

    name = "url-guard"
    stages = {GuardrailStage.TOOL_CALL}
    priority = 10

    def __init__(self) -> None:
        self.seen: list[dict] = []

    async def check(self, content, ctx):
        self.seen.append({"tool": ctx.tool_name, "studio": ctx.extras.get("studio"), "args": ctx.extras["arguments"]})
        if "127.0.0.1" in str(ctx.extras["arguments"]):
            return GuardrailResult(action=GuardrailAction.BLOCK, reason="egress_blocked: loopback address")
        return GuardrailResult(action=GuardrailAction.PASS)


class Exploding(Guardrail):
    name = "exploding"
    stages = {GuardrailStage.TOOL_CALL}
    priority = 20
    on_error = "fail_open"          # the host's own setting must not open the call

    async def check(self, content, ctx):
        raise RuntimeError("dns resolver down")


def _app(pool, guardrails=None):  # noqa: F811
    app = tenant_app(pool)
    set_tenant_tooling_policy(app, TenantToolingPolicy(builtin_tools=frozenset({"calculator"})))
    if guardrails is not None:
        app[STUDIO_TOOL_CALL_GUARDRAILS] = guardrails
    return app


async def _agent(client, caller, name="mine"):
    resp, body = await create(client, name, caller, llm=f"{PROVIDER}:m", config={"tools": ["calculator"]})
    assert resp.status == 201, body


async def _live_bot(client, caller, name="mine"):
    resp = await client.post(f"{BASE}/agents/{name}/test/ask", json={"query": "hi"}, headers=caller)
    assert resp.status == 200, await resp.text()
    entries = [e for e in client.app["bot_manager"].studio._cache.all_entries() if e.bot.name == name]
    return entries[-1].bot


async def _call(bot, args):
    return await bot.tool_manager.execute_tool(TOOL, args, return_tool_result=True)


def test_feature_probe():
    assert "tool_call_guardrails" in FEATURES


async def test_a_blocking_guardrail_refuses_the_call_and_a_passing_one_changes_nothing(aiohttp_client, pool):  # noqa: F811
    guard = UrlGuard()
    client = await aiohttp_client(_app(pool, [guard]))
    caller = who("u1")
    await _agent(client, caller)
    bot = await _live_bot(client, caller)
    blocked = await _call(bot, BAD)
    assert blocked.success is False and blocked.status == "forbidden"
    assert "egress_blocked" in blocked.error                        # the message reaches the LLM
    passed = await _call(bot, GOOD)
    assert passed.status != "forbidden"
    assert [s["args"] for s in guard.seen] == [BAD, GOOD] and guard.seen[0]["tool"] == TOOL


async def test_a_raising_guardrail_fails_closed(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool, [Exploding()]))
    caller = who("u1")
    await _agent(client, caller)
    bot = await _live_bot(client, caller)
    refused = await _call(bot, GOOD)
    assert refused.status == "forbidden" and "guardrail_error:exploding" in refused.error


async def test_each_tenants_bot_sees_its_own_context(aiohttp_client, pool):  # noqa: F811
    guard = UrlGuard()
    client = await aiohttp_client(_app(pool, [guard]))
    for caller in (who("u1", "acme"), who("u9", "globex")):
        await _agent(client, caller)
        bot = await _live_bot(client, caller)
        await _call(bot, GOOD)
    tenants = [seen["studio"]["tenant"] for seen in guard.seen]
    assert tenants == ["acme", "globex"]
    assert all(seen["studio"]["agent"] == "mine" and seen["studio"]["agent_id"] for seen in guard.seen)
    assert guard.seen[0]["studio"]["agent_id"] != guard.seen[1]["studio"]["agent_id"]


async def test_without_guardrails_nothing_changes(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    caller = who("u1")
    await _agent(client, caller)
    bot = await _live_bot(client, caller)
    assert (await _call(bot, BAD)).status != "forbidden"


async def test_a_per_session_clone_keeps_the_guardrails(aiohttp_client, pool):  # noqa: F811
    guard = UrlGuard()
    client = await aiohttp_client(_app(pool, [guard]))
    caller = who("u1")
    await _agent(client, caller)
    bot = await _live_bot(client, caller)
    clone = bot.tool_manager.clone()
    blocked = await clone.execute_tool(TOOL, BAD, return_tool_result=True)
    assert blocked.status == "forbidden"


async def test_the_direct_execute_route_is_guarded_too(aiohttp_client, pool):  # noqa: F811
    guard = UrlGuard()
    client = await aiohttp_client(_app(pool, [guard]))
    caller = who("u1")
    resp = await client.post(f"{BASE}/tools/calculator/execute", json={"args": BAD}, headers=caller)
    body = await resp.json()
    assert resp.status == 403 and body["code"] == "tool_call_blocked" and "egress_blocked" in body["message"], body
    assert guard.seen[-1]["studio"] == {"tenant": "acme", "agent_id": None, "agent": None, "visibility": None}
    resp = await client.post(f"{BASE}/tools/calculator/execute", json={"args": GOOD}, headers=caller)
    assert resp.status != 403
