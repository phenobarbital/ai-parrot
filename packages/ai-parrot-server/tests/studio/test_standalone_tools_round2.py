"""Integration round 2: standalone ``AbstractTool``s attached to a Studio agent really run, on every path.

Real app, real routes, real Postgres and the real runtime build. The host probe tools (``tp_probe_tool``: no
params, ``tp_probe_managed``: a constructor dependency the server fills from ``app['probe_store']``) and the real
``CSVExportTool`` over a real ``ArtifactStore`` are the tools; the hook and the guardrail are host code; only the LLM
client is test-owned (scripted).

Construction paths covered: persisted spec (``PUT /toolkits/{slug}``), definition ``config.tools``, live
``POST /toolkits`` and live ``POST /tools``.
"""
from __future__ import annotations

import pytest
from navigator.utils.file import LocalFileManager

import parrot.tools.exports_mode as exports_mode
from parrot.bots.guardrails.base import Guardrail, GuardrailAction, GuardrailResult, GuardrailStage
from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.handlers import tools_catalog as tools_catalog_module
from parrot.handlers.studio import STUDIO_TOOL_CALL_GUARDRAILS, STUDIO_TOOLKIT_PARAM_HOOK, agents as agents_module
from parrot.handlers.studio import catalog as catalog_module
from parrot.registry import registry as registry_module
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.overflow import OverflowStore
from parrot.tools.tooling_policy import TenantToolingPolicy, ToolParamRefused, set_tenant_tooling_policy

from ._host_probe import host_plugins  # noqa: F401  (fixture)
from ._scripted_llm import PROVIDER, ScriptedClient
from .test_agents_db_mode import BASE, pool  # noqa: F401  (fixture)
from .test_agents_visibility import create, tenant_app, who

OWNER = who("u1")  # tenant acme
SENTINEL = object()
PATHS = ["spec", "config_tools", "live_toolkits", "live_tools"]


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setitem(SUPPORTED_CLIENTS, PROVIDER, ScriptedClient)
    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("STUDIO_SWEEP_INTERVAL_SECONDS", "3600")
    monkeypatch.setattr(agents_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(catalog_module, "_BASE_CLASSES_CACHE", None)
    monkeypatch.setattr(tools_catalog_module, "_CATALOG_CACHE", None)
    yield
    exports_mode.configure(False)


class BlockAll(Guardrail):
    """Host TOOL_CALL guardrail: blocks every call and records the tool names it saw."""

    name = "block-all"
    stages = {GuardrailStage.TOOL_CALL}
    priority = 10

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def check(self, content, ctx):
        self.seen.append(ctx.tool_name)
        return GuardrailResult(action=GuardrailAction.BLOCK, reason="blocked_by_host")


def _store(tmp_path):
    return ArtifactStore(
        dynamodb=ConversationSQLiteBackend(str(tmp_path / "c.db")),
        s3_overflow=OverflowStore(LocalFileManager(base_path=tmp_path / "files")),
    )


def _app(pool, *, hook=None, guard=None, store=None, resolver=True):  # noqa: F811
    app = tenant_app(pool, resolver=resolver)
    set_tenant_tooling_policy(app, TenantToolingPolicy(builtin_tools=frozenset({"csv_export"})))
    if hook is not None:
        app[STUDIO_TOOLKIT_PARAM_HOOK] = hook
    if guard is not None:
        app[STUDIO_TOOL_CALL_GUARDRAILS] = [guard]
    app["probe_store"] = SENTINEL
    if store is not None:  # the host's store-only exports + its artifact store
        app["artifact_store"] = store
        app[exports_mode.STUDIO_EXPORTS_STORE_ONLY] = True
    return app


async def _create(client, name="mine", caller=OWNER, **extra):
    resp, body = await create(client, name, caller, llm=f"{PROVIDER}:m", **extra)
    assert resp.status == 201, body


async def _put(client, slug, params=None, name="mine"):
    resp = await client.put(f"{BASE}/agents/{name}/toolkits/{slug}", json={"params": params or {}}, headers=OWNER)
    assert resp.status == 200, await resp.text()


async def _start(client, name="mine"):
    resp = await client.post(f"{BASE}/agents/{name}/test/ask", json={"query": "hi"}, headers=OWNER)
    assert resp.status == 200, await resp.text()
    (entry,) = [e for e in client.app["bot_manager"].studio._cache.all_entries() if e.bot.name == name]
    return entry.bot


async def _bot_via(client, path, slug):
    """A bot carrying ``slug`` attached through ``path`` (the live paths use the global, untenanted partition)."""
    if path == "spec":
        await _create(client)
        await _put(client, slug)
        return await _start(client)
    if path == "config_tools":
        await _create(client, config={"tools": [slug]})
        return await _start(client)
    caller = who("u1", None)
    await _create(client, caller=caller)
    bot = await client.app["bot_manager"].get_bot("mine")
    if path == "live_toolkits":
        resp = await client.post(f"{BASE}/agents/mine/toolkits", json={"slug": slug, "params": {}}, headers=caller)
    else:
        resp = await client.post(f"{BASE}/agents/mine/tools", json={"tools": [slug]}, headers=caller)
    assert resp.status == 200, await resp.text()
    return bot


async def _call(bot, name, args=None):
    return await bot.tool_manager.execute_tool(name, args or {}, return_tool_result=True)


async def test_a_standalone_tool_put_through_the_ui_is_built_and_callable(aiohttp_client, pool, host_plugins):  # noqa: F811
    """P5: ``PUT /toolkits/{slug}`` of an AbstractTool used to be swallowed (``Invalid toolkit type``)."""
    client = await aiohttp_client(_app(pool))
    await _create(client)
    await _put(client, "tp_probe_tool")
    bot = await _start(client)
    assert "tp_probe_tool" in bot.tool_manager.list_tools()
    result = await _call(bot, "tp_probe_tool", {"value": "x"})
    assert result.success is True and bot.tooling_failures == []
    resp = await client.get(f"{BASE}/agents/mine/toolkit-config", headers=OWNER)
    body = await resp.json()
    assert resp.status == 200 and body["failed"] == [] and body["unavailable"] == [], body


async def test_a_spec_that_cannot_be_applied_is_reported_not_silently_skipped(  # noqa: F811
    aiohttp_client, pool, host_plugins
):
    """No ``app['probe_store']``: the tool's server-managed constructor dependency is missing, the build cannot apply it."""
    app = _app(pool)
    del app["probe_store"]
    client = await aiohttp_client(app)
    await _create(client)
    await _put(client, "tp_probe_managed")             # the write validates what it can: the store is server-owned
    bot = await _start(client)                         # the agent still boots, without that tool ...
    assert "tp_probe_managed" not in bot.tool_manager.list_tools()
    (failure,) = bot.tooling_failures                  # ... and the failure is recorded on the bot
    assert failure["slug"] == "tp_probe_managed" and "store" in failure["error"]
    resp = await client.get(f"{BASE}/agents/mine/toolkit-config", headers=OWNER)
    body = await resp.json()
    assert body["failed"] == [failure], body           # ... and the API says so


@pytest.mark.parametrize("path", ["spec", "live_toolkits"])
async def test_a_server_managed_dependency_is_filled_on_the_toolkit_paths(  # noqa: F811
    aiohttp_client, pool, host_plugins, path
):
    """P6 with a host tool whose constructor REQUIRES an app-sourced dependency (no default)."""
    client = await aiohttp_client(_app(pool, resolver=path == "spec"))
    bot = await _bot_via(client, path, "tp_probe_managed")
    tool = bot.tool_manager.get_tool("tp_probe_managed")
    assert tool is not None and tool.store is SENTINEL


@pytest.mark.parametrize("path", PATHS)
async def test_an_export_tool_writes_through_the_configured_store_on_each_path(  # noqa: F811
    aiohttp_client, pool, tmp_path, path
):
    """P6, the real thing: ``csv_export`` (store optional in its constructor) publishes to the artifact store on
    every path that builds it for a Studio agent and returns the store's URL."""
    store = _store(tmp_path)
    client = await aiohttp_client(_app(pool, store=store, resolver=path in ("spec", "config_tools")))
    bot = await _bot_via(client, path, "csv_export")
    assert bot.tool_manager.get_tool("csv_export").artifact_store is store
    result = await _call(bot, "csv_export", {"content": [{"a": 1, "b": 2}]})
    assert result.success is True, result.error
    assert "/exports/" in str(result.result), result.result


@pytest.mark.parametrize("path", PATHS)
async def test_the_param_hook_sees_the_final_params_on_every_path(aiohttp_client, pool, tmp_path, path):  # noqa: F811
    """PA-9 on a standalone tool: keyed by the canonical slug, and it sees the server fill (the store)."""
    seen: list[tuple] = []

    def hook(slug, params, subject):
        seen.append((slug, "artifact_store" in params, subject.phase))
        return params

    client = await aiohttp_client(_app(pool, hook=hook, store=_store(tmp_path), resolver=path in ("spec", "config_tools")))
    await _bot_via(client, path, "csv_export")
    assert [s for s in seen if s[0] == "csv_export" and s[1]], seen


@pytest.mark.parametrize("path", PATHS)
async def test_a_refusing_hook_builds_nothing_on_any_path(aiohttp_client, pool, tmp_path, path):  # noqa: F811
    def hook(slug, params, subject):
        raise ToolParamRefused(["artifact_store"])

    client = await aiohttp_client(_app(pool, hook=hook, store=_store(tmp_path), resolver=path in ("spec", "config_tools")))
    if path == "spec":
        await _create(client)
        resp = await client.put(f"{BASE}/agents/mine/toolkits/csv_export", json={"params": {}}, headers=OWNER)
        assert resp.status == 422, await resp.text()
        return
    if path == "config_tools":
        await _create(client, config={"tools": ["csv_export"]})
        bot = await _start(client)  # as PA-9: a refused ``config.tools`` entry is never built, the agent still boots
        assert bot.tool_manager.get_tool("csv_export") is None
        assert [f["slug"] for f in bot.tooling_failures] == ["csv_export"]  # ... and it is reported, not skipped
        return
    caller = who("u1", None)
    await _create(client, caller=caller)
    bot = await client.app["bot_manager"].get_bot("mine")
    url, body = (
        (f"{BASE}/agents/mine/toolkits", {"slug": "csv_export", "params": {}})
        if path == "live_toolkits"
        else (f"{BASE}/agents/mine/tools", {"tools": ["csv_export"]})
    )
    resp = await client.post(url, json=body, headers=caller)
    assert resp.status == 422, await resp.text()
    assert bot.tool_manager.get_tool("csv_export") is None


@pytest.mark.parametrize("path", ["spec", "config_tools"])
async def test_the_call_guardrails_stand_in_front_of_a_standalone_tool(aiohttp_client, pool, tmp_path, path):  # noqa: F811
    """PA-10 on a standalone tool built by the Studio runtime from a spec or from ``config.tools``."""
    guard = BlockAll()
    client = await aiohttp_client(_app(pool, guard=guard, store=_store(tmp_path)))
    bot = await _bot_via(client, path, "csv_export")
    blocked = await _call(bot, "csv_export", {"content": [{"a": 1}]})
    assert blocked.status == "forbidden" and "blocked_by_host" in blocked.error
    assert guard.seen == ["csv_export"]


@pytest.mark.parametrize("path", ["live_toolkits", "live_tools"])
async def test_a_live_attached_tool_joins_the_bots_guarded_tool_manager(  # noqa: F811
    aiohttp_client, pool, tmp_path, path
):
    """PA-10 on the live-assign routes: the tool is registered in the live bot's own manager, whose TOOL_CALL
    pipeline (bound as the Studio builder binds it) stands in front of it."""
    from parrot.tools.host_hooks import bind_host_tool_call_guardrails

    guard = BlockAll()
    client = await aiohttp_client(_app(pool, store=_store(tmp_path), resolver=False))
    caller = who("u1", None)
    await _create(client, caller=caller)
    bot = await client.app["bot_manager"].get_bot("mine")
    bind_host_tool_call_guardrails(
        bot._guardrail_pipelines[GuardrailStage.TOOL_CALL], [guard], {"tenant": None, "agent": "mine"}
    )
    url, body = (
        (f"{BASE}/agents/mine/toolkits", {"slug": "csv_export", "params": {}})
        if path == "live_toolkits"
        else (f"{BASE}/agents/mine/tools", {"tools": ["csv_export"]})
    )
    resp = await client.post(url, json=body, headers=caller)
    assert resp.status == 200, await resp.text()
    blocked = await _call(bot, "csv_export", {"content": [{"a": 1}]})
    assert blocked.status == "forbidden" and guard.seen == ["csv_export"]
