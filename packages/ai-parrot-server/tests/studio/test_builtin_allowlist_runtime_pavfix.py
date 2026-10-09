"""PA-V2 review fix 7: a stored agent calling a built-in the tenant no longer has is refused AT CALL TIME.

Real app, real runtime build of the stored agent, real ``ToolManager.execute_tool`` pipeline; only the LLM client is
test-owned (scripted). The tenant callback is host code reading a mutable set, so the allow-list can shrink after the
agent was stored and built.
"""
from __future__ import annotations

import pytest

from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.handlers import tools_catalog as tools_catalog_module
from parrot.handlers.studio import agents as agents_module
from parrot.handlers.studio import catalog as catalog_module
from parrot.registry import registry as registry_module
from parrot.tools.tooling_policy import TenantToolingPolicy, set_tenant_tooling_policy

from ._scripted_llm import PROVIDER, ScriptedClient
from .test_agents_db_mode import BASE, pool  # noqa: F401  (fixture)
from .test_agents_visibility import create, tenant_app, who

TOOL = "CalculatorTool"
ARGS = {"operation": "add", "x": 1.0, "y": 2.0}


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setitem(SUPPORTED_CLIENTS, PROVIDER, ScriptedClient)
    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("STUDIO_SWEEP_INTERVAL_SECONDS", "3600")
    monkeypatch.setattr(agents_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(catalog_module, "_BASE_CLASSES_CACHE", None)
    monkeypatch.setattr(tools_catalog_module, "_CATALOG_CACHE", None)


async def _stored_bot(client, caller, name="mine"):
    resp, body = await create(client, name, caller, llm=f"{PROVIDER}:m", config={"tools": ["calculator"]})
    assert resp.status == 201, body
    resp = await client.post(f"{BASE}/agents/{name}/test/ask", json={"query": "hi"}, headers=caller)
    assert resp.status == 200, await resp.text()
    return [e for e in client.app["bot_manager"].studio._cache.all_entries() if e.bot.name == name][-1].bot


async def _call(bot):
    return await bot.tool_manager.execute_tool(TOOL, ARGS, return_tool_result=True)


async def test_a_builtin_removed_from_the_tenant_list_is_refused_when_the_stored_agent_calls_it(  # noqa: F811
    aiohttp_client, pool
):
    enabled = {"calculator"}
    app = tenant_app(pool)
    set_tenant_tooling_policy(app, TenantToolingPolicy(
        builtin_tools=frozenset({"calculator", "arxiv"}),
        tenant_builtin_tools=lambda tenant: set(enabled) if tenant == "acme" else None,
    ))
    client = await aiohttp_client(app)
    acme, globex = who("u1", "acme"), who("u9", "globex")
    bot = await _stored_bot(client, acme)
    other = await _stored_bot(client, globex, "theirs")
    assert (await _call(bot)).status != "forbidden"                         # enabled: the call goes through
    enabled.clear()                                                         # ops remove it from acme's allow-list
    refused = await _call(bot)
    assert refused.success is False and refused.status == "forbidden"
    assert "builtin_not_permitted" in refused.error and "calculator" in refused.error
    assert (await _call(other)).status != "forbidden"                       # another tenant is untouched


async def test_a_host_without_the_callbacks_registers_no_guardrail(aiohttp_client, pool):  # noqa: F811
    app = tenant_app(pool)
    set_tenant_tooling_policy(app, TenantToolingPolicy(builtin_tools=frozenset({"calculator"})))
    client = await aiohttp_client(app)
    bot = await _stored_bot(client, who("u1"))
    from parrot.bots.guardrails.base import GuardrailStage

    assert not bot._guardrail_pipelines[GuardrailStage.TOOL_CALL].has_guardrails
    assert (await _call(bot)).status != "forbidden"
