"""PA-9: the host toolkit-parameter hook on every construction path.

Real app, real routes, real Postgres and the real runtime build; the host probe toolkit ``tp_probe`` is the
toolkit, a plain callable is the host hook, and only the LLM client is test-owned (scripted).
"""
from __future__ import annotations

import pytest

from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.handlers import tools_catalog as tools_catalog_module
from parrot.handlers.studio import STUDIO_TOOLKIT_PARAM_HOOK, agents as agents_module
from parrot.handlers.studio import catalog as catalog_module
from parrot.registry import registry as registry_module
from parrot.tools.host_hooks import FEATURES
from parrot.tools.manager import get_toolkit_owner
from parrot.tools.tooling_policy import TenantToolingPolicy, ToolParamRefused, set_tenant_tooling_policy

from ._host_probe import host_plugins  # noqa: F401  (fixture)
from ._scripted_llm import PROVIDER, ScriptedClient
from .test_agents_db_mode import BASE, pool  # noqa: F401  (fixture)
from .test_agents_visibility import create, tenant_app, who
from .test_drafts_tenant import _drafts_dir, activate, save  # noqa: F401  (fixtures)

SLUG = "tp_probe"
FORCED = 7
CLIENT = 123
OWNER = who("u1")  # tenant acme


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setitem(SUPPORTED_CLIENTS, PROVIDER, ScriptedClient)
    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("STUDIO_SWEEP_INTERVAL_SECONDS", "3600")
    monkeypatch.setattr(agents_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(catalog_module, "_BASE_CLASSES_CACHE", None)
    monkeypatch.setattr(tools_catalog_module, "_CATALOG_CACHE", None)


class Host:
    """A host hook: refuses ``base_url`` while ``refuse`` is on; forces ``remote_timeout_seconds`` and
    ``exclude_tools`` for tp_probe."""

    def __init__(self) -> None:
        self.refuse = True
        self.calls: list[tuple] = []

    def __call__(self, slug, params, subject):
        self.calls.append((slug, dict(params), subject.phase, subject.tenant, subject.agent_id))
        if self.refuse and "base_url" in params:
            raise ToolParamRefused(["base_url"])
        if slug == SLUG:
            return {**params, "remote_timeout_seconds": FORCED, "exclude_tools": ("bump",)}
        return params


def _app(pool, hook=None):  # noqa: F811
    app = tenant_app(pool)
    set_tenant_tooling_policy(app, TenantToolingPolicy())
    if hook is not None:
        app[STUDIO_TOOLKIT_PARAM_HOOK] = hook
    return app


async def _agent(client, name="mine", **extra):
    resp, body = await create(client, name, OWNER, llm=f"{PROVIDER}:m", **extra)
    assert resp.status == 201, body


async def _put(client, params, name="mine", slug=SLUG):
    resp = await client.put(f"{BASE}/agents/{name}/toolkits/{slug}", json={"params": params}, headers=OWNER)
    return resp, await resp.json()


async def _start(client, name="mine"):
    """Build the stored agent through the real runtime (a test turn) and return the live bot, or the response."""
    resp = await client.post(f"{BASE}/agents/{name}/test/ask", json={"query": "hi"}, headers=OWNER)
    if resp.status != 200:
        return resp, await resp.json()
    (entry,) = [e for e in client.app["bot_manager"].studio._cache.all_entries() if e.bot.name == name]
    return resp, entry.bot


def _toolkit(bot):
    return get_toolkit_owner(bot.tool_manager.get_tool("tp_whoami"))


def test_feature_probe():
    assert "toolkit_param_hook" in FEATURES


async def test_write_refuses_a_param_the_hook_refuses(aiohttp_client, pool, host_plugins):  # noqa: F811
    host = Host()
    client = await aiohttp_client(_app(pool, host))
    await _agent(client)
    resp, body = await _put(client, {"base_url": "http://evil.example"})
    assert resp.status == 422 and body["code"] == "tooling_not_permitted", body
    assert body["details"] == {"reason": "tool_params_not_permitted", "item": SLUG, "params": ["base_url"]}
    resp, body = await _put(client, {"remote_timeout_seconds": 11})
    assert resp.status == 200, body
    assert (SLUG, {"remote_timeout_seconds": 11}, "write", "acme", None) in [c[:4] + (None,) for c in host.calls]


async def test_assign_forces_values_and_exclude_tools(aiohttp_client, pool, host_plugins):  # noqa: F811
    """A live assignment exists on the GLOBAL partition only (a tenant agent persists its tooling instead)."""
    host = Host()
    app = tenant_app(pool, resolver=False)
    app[STUDIO_TOOLKIT_PARAM_HOOK] = host
    client = await aiohttp_client(app)
    caller = who("u1", None)
    resp, body = await create(client, "mine", caller, llm=f"{PROVIDER}:m")
    assert resp.status == 201, body
    bot = await client.app["bot_manager"].get_bot("mine")
    assert bot is not None
    url = f"{BASE}/agents/mine/toolkits"
    resp = await client.post(url, json={"slug": SLUG, "params": {"base_url": "http://x"}}, headers=caller)
    body = await resp.json()
    assert resp.status == 422 and body["details"] == {
        "reason": "tool_params_not_permitted", "item": SLUG, "params": ["base_url"]}, body
    assert bot.tool_manager.get_tool("tp_whoami") is None  # a refused request registered nothing
    resp = await client.post(url, json={"slug": SLUG, "params": {"remote_timeout_seconds": CLIENT}}, headers=caller)
    body = await resp.json()
    assert resp.status == 200, body
    assert "tp_whoami" in body["registered_tools"] and "tp_bump" not in body["registered_tools"]
    toolkit = _toolkit(bot)
    assert toolkit.remote_timeout_seconds == FORCED   # whatever the client sent
    assert bot.tool_manager.get_tool("tp_bump") is None and "bump" in toolkit.exclude_tools
    assert [c for c in host.calls if c[2] == "attach"] and host.calls[-1][3] is None


async def test_a_stored_agent_is_built_through_the_hook(aiohttp_client, pool, host_plugins):  # noqa: F811
    host = Host()
    client = await aiohttp_client(_app(pool, host))
    await _agent(client)
    assert (await _put(client, {"remote_timeout_seconds": CLIENT}))[0].status == 200
    resp, bot = await _start(client)
    assert resp.status == 200
    toolkit = _toolkit(bot)
    assert toolkit.remote_timeout_seconds == FORCED and bot.tool_manager.get_tool("tp_bump") is None
    assert any(c[2] == "build" and c[0] == SLUG and c[4] is not None for c in host.calls)  # build phase, agent id


async def test_a_stored_row_cannot_smuggle_a_param_past_the_build(aiohttp_client, pool, host_plugins):  # noqa: F811
    host = Host()
    host.refuse = False                           # the hook allowed it when the row was written
    client = await aiohttp_client(_app(pool, host))
    await _agent(client)
    assert (await _put(client, {"base_url": "http://evil.example"}))[0].status == 200
    host.refuse = True                            # the host tightened since: the stored agent must not build
    resp, body = await _start(client)
    assert resp.status == 422 and body["code"] == "tooling_not_permitted", body
    assert body["details"] == {"reason": "tool_params_not_permitted", "item": SLUG, "params": ["base_url"]}
    # an unrelated edit of the agent stays possible: only toolkits added or re-configured are re-checked on write
    resp = await client.patch(f"{BASE}/agents/mine", json={"description": "still editable"}, headers=OWNER)
    assert resp.status == 200, await resp.text()
    resp, _ = await _put(client, {"base_url": "http://evil.example"})  # re-configured: checked again
    assert resp.status == 422


async def test_draft_activation_is_checked(aiohttp_client, pool, host_plugins):  # noqa: F811
    host = Host()
    host.refuse = False
    client = await aiohttp_client(_app(pool, host))
    extra = {"toolkits": [{"slug": SLUG, "params": {"base_url": "http://evil.example"}}]}
    assert (await save(client, "d1", OWNER, bundle_extra=extra))[0].status == 201
    host.refuse = True
    resp, body = await activate(client, "d1", OWNER)
    assert resp.status == 422 and body["details"]["reason"] == "tool_params_not_permitted", body
    assert body["details"]["params"] == ["base_url"]


@pytest.mark.parametrize(
    "hook",
    [lambda s, p, subj: 1 / 0, lambda s, p, subj: None, lambda s, p, subj: {**p, "exclude_tools": "bump"}],
    ids=["raises", "not-a-mapping", "malformed-exclude"],
)
async def test_a_broken_hook_fails_closed(aiohttp_client, pool, host_plugins, hook):  # noqa: F811
    client = await aiohttp_client(_app(pool, hook))
    await _agent(client)
    resp, body = await _put(client, {"remote_timeout_seconds": 5})
    assert resp.status == 422 and body["details"]["reason"] == "tool_params_not_permitted", body


async def test_an_async_hook_fails_closed(aiohttp_client, pool, host_plugins):  # noqa: F811
    async def hook(slug, params, subject):
        return params

    client = await aiohttp_client(_app(pool, hook))
    await _agent(client)
    resp, body = await _put(client, {"remote_timeout_seconds": 5})
    assert resp.status == 422 and body["details"]["reason"] == "tool_params_not_permitted", body


async def test_without_a_hook_nothing_changes(aiohttp_client, pool, host_plugins):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    await _agent(client)
    assert (await _put(client, {"base_url": "http://ok.example", "remote_timeout_seconds": CLIENT}))[0].status == 200
    resp, bot = await _start(client)
    assert resp.status == 200
    toolkit = _toolkit(bot)
    # nothing forced: every tool stays, and a param the constructor does not declare is dropped at build as before
    assert toolkit.remote_timeout_seconds == 300 and bot.tool_manager.get_tool("tp_bump") is not None


async def test_a_tool_named_in_tools_goes_through_the_hook(aiohttp_client, pool):  # noqa: F811
    """``definition.tools`` names no params at all, but the hook still sees (and can refuse) the tool at build."""
    seen: list[tuple] = []

    def hook(slug, params, subject):
        seen.append((slug, dict(params), subject.phase))
        if slug == "arxiv":
            raise ToolParamRefused([])
        return params

    app = tenant_app(pool)
    set_tenant_tooling_policy(app, TenantToolingPolicy(builtin_tools=frozenset({"calculator", "arxiv"})))
    app[STUDIO_TOOLKIT_PARAM_HOOK] = hook
    client = await aiohttp_client(app)
    await _agent(client, config={"tools": ["calculator", "arxiv"]})
    resp, bot = await _start(client)
    assert resp.status == 200
    assert ("calculator", {}, "build") in seen and ("arxiv", {}, "build") in seen
    names = [name.lower() for name in bot.tool_manager.list_tools()]
    assert any("calculator" in name for name in names)
    assert not any("arxiv" in name for name in names)             # refused by the hook: never constructed
