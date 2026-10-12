"""PA-V2 review fix 3: a host-forced ``confine_sources`` reaches the wiki toolkit built by the Studio assign route.

Real app, real assign handler, real ``LLMWikiToolkit`` / PageIndex / GraphIndex; the hook is host code (test-owned).
"""
from __future__ import annotations

import pytest

from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.handlers import tools_catalog as tools_catalog_module
from parrot.handlers.studio import STUDIO_TOOLKIT_PARAM_HOOK, agents as agents_module
from parrot.handlers.studio import catalog as catalog_module
from parrot.registry import registry as registry_module
from parrot.tools.manager import get_toolkit_owner
from parrot.tools.tooling_policy import TenantToolingPolicy, set_tenant_tooling_policy

from ._scripted_llm import PROVIDER, ScriptedClient
from .test_agents_db_mode import BASE, pool  # noqa: F401  (fixture)
from .test_agents_visibility import create, tenant_app, who

OWNER = who("u1", None)


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setitem(SUPPORTED_CLIENTS, PROVIDER, ScriptedClient)
    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("STUDIO_SWEEP_INTERVAL_SECONDS", "3600")
    monkeypatch.setattr(agents_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(catalog_module, "_BASE_CLASSES_CACHE", None)
    monkeypatch.setattr(tools_catalog_module, "_CATALOG_CACHE", None)


async def _assign_wiki(aiohttp_client, pool, tmp_path, hook):  # noqa: F811
    app = tenant_app(pool, resolver=False)  # a live assignment exists on the global partition only
    set_tenant_tooling_policy(app, TenantToolingPolicy())
    if hook is not None:
        app[STUDIO_TOOLKIT_PARAM_HOOK] = hook
    client = await aiohttp_client(app)
    resp, body = await create(client, "mine", OWNER, llm=f"{PROVIDER}:m")
    assert resp.status == 201, body
    bot = await client.app["bot_manager"].get_bot("mine")
    params = {"wiki_name": "w", "storage_dir": str(tmp_path / "wiki")}
    resp = await client.post(f"{BASE}/agents/mine/toolkits", json={"slug": "wiki", "params": params}, headers=OWNER)
    body = await resp.json()
    assert resp.status == 200, body
    name = next(n for n in body["registered_tools"] if n.endswith("ingest_source"))
    return get_toolkit_owner(bot.tool_manager.get_tool(name))


async def test_a_host_forced_confine_sources_reaches_the_assigned_wiki(aiohttp_client, pool, tmp_path):  # noqa: F811
    seen = []

    def hook(slug, params, subject):
        seen.append(slug)
        return {**params, "confine_sources": True}

    toolkit = await _assign_wiki(aiohttp_client, pool, tmp_path, hook)
    assert seen == ["wiki"] and toolkit.confine_sources is True
    secret = tmp_path / "secret.md"
    secret.write_text("# secret")
    with pytest.raises(ValueError, match="outside the permitted"):
        await toolkit.ingest_source("w", str(secret))                       # outside <storage_dir>/sources
    with pytest.raises(ValueError, match="outside the permitted"):
        await toolkit.export_okf("w", output_dir=str(tmp_path / "elsewhere"))


async def test_without_a_hook_the_wiki_is_unconfined(aiohttp_client, pool, tmp_path):  # noqa: F811
    toolkit = await _assign_wiki(aiohttp_client, pool, tmp_path, None)
    assert toolkit.confine_sources is False
