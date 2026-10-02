"""FEAT-621 M9 assistant tools on the Studio services (AC4, AC13, AC15).

Real aiohttp app with a real Postgres pool; the tools run inside a real ``RequestContext`` bound the way
``AbstractBot.session()`` binds it. ``AbstractBot.configure`` is replaced (see ``test_agents_db_mode``).
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.bots.studio import tools as tools_module
from parrot.bots.studio.agent import AgentStudioAgent
from parrot.handlers.studio.storage.models import StudioPartition
from parrot.utils.helpers import RequestContext, _current_ctx

from .test_agents_db_mode import _app, _offline, pool  # noqa: F401  (fixtures)

KB = "kb"
T1 = SimpleNamespace(caller=SimpleNamespace(tenant="t1"))


@contextmanager
def _ctx(app, user_id="u1", scope=None):
    extra = {"studio_scope": scope} if scope is not None else {}
    token = _current_ctx.set(RequestContext(app=app, user_id=user_id, **extra))
    try:
        yield
    finally:
        _current_ctx.reset(token)


async def _call(tool_fn, **kwargs):
    return await tool_fn._tool_metadata["function"](**kwargs)


def _names(tools):
    return {t._tool_metadata["name"] for t in tools}


def _agent(**kwargs):
    from unittest.mock import MagicMock

    from parrot.clients.anthropic import AnthropicClient

    return AgentStudioAgent(name="t", llm=MagicMock(spec=AnthropicClient), **kwargs)


def test_assistant_toolset_per_partition():
    tenant = _names(_agent(declarative_only=True).agent_tools())
    assert "save_agent_draft" not in tenant and "save_agent_bundle" in tenant
    assert _names(tools_module.build_studio_tools(declarative_only=True)) >= {"create_yaml_agent", "write_kb_file"}


def test_global_toolset_unchanged():
    names = _names(_agent().agent_tools())
    assert "save_agent_draft" in names and "save_agent_bundle" not in names
    assert _names(tools_module.build_studio_tools()) == _names(tools_module.build_studio_tools(declarative_only=False))
    assert len(tools_module.build_studio_tools()) == 9


async def test_handler_builds_toolset_from_partition_policy(aiohttp_client, pool, monkeypatch):  # noqa: F811
    from parrot.handlers.studio.meta_agent import StudioAssistantHandler

    client = await aiohttp_client(_app(pool))
    drafts = client.app["studio_storage"].services.drafts
    handler = StudioAssistantHandler(make_mocked_request("POST", "/assistant", app=client.app))

    async def _tenant():
        return StudioPartition("t1")

    async def _global():
        return StudioPartition.GLOBAL

    monkeypatch.setattr(handler, "_studio_partition", _tenant, raising=False)
    assert await handler._declarative_only() is True
    monkeypatch.setattr(handler, "_studio_partition", _global, raising=False)
    assert await handler._declarative_only() is not drafts.python_drafts_allowed(StudioPartition.GLOBAL)
    bare = StudioAssistantHandler(make_mocked_request("POST", "/assistant", app=web.Application()))
    assert await bare._declarative_only() is False


async def test_tools_write_through_services(aiohttp_client, pool, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(tools_module, "AGENTS_DIR", tmp_path / "agents_dir")
    client = await aiohttp_client(_app(pool))
    app = client.app
    services = app["studio_storage"].services
    with _ctx(app):
        made = await _call(tools_module.create_yaml_agent, name="alpha", bot_class="BasicBot", description="d")
        assert made["agent_name"] == "alpha" and made["source"] == "studio" and made["version"] == 1
        rec = await services.agents.get(StudioPartition.GLOBAL, "alpha")
        assert rec.owner == "u1" and rec.definition.description == "d"
        res = await _call(tools_module.write_kb_file, agent_name="alpha", filename="n.md", content="hello")
        assert res["size"] == 5 and res["kind"] == KB
        asset = await services.assets.get(StudioPartition.GLOBAL, "alpha", KB, "n.md")
        assert asset.content == "hello"
        skill = await _call(
            tools_module.publish_skill_to_catalog, name="s1", description="x", category="general", triggers=["/s"],
            body="---\nname: s1\ndescription: x\n---\nbody",
        )
        assert skill["owner"] == "u1" and skill["tenant"] is None
        dup = await _call(tools_module.create_yaml_agent, name="alpha", bot_class="BasicBot")
        assert dup["error_code"] == "duplicate"
        with pytest.raises(ValueError):
            await _call(tools_module.create_yaml_agent, name="beta", bot_class="NoSuchClass")
    with _ctx(app, user_id="intruder"):
        with pytest.raises(PermissionError):
            await _call(tools_module.write_kb_file, agent_name="alpha", filename="n.md", content="hijack")
    assert (await services.assets.get(StudioPartition.GLOBAL, "alpha", KB, "n.md")).content == "hello"
    assert not (tmp_path / "agents_dir").exists()


async def test_save_agent_bundle_policy_refusal(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    app = client.app
    services = app["studio_storage"].services
    ok = {"definition": {"bot_class": "BasicBot", "description": "t"}}
    with _ctx(app, scope=T1):
        saved = await _call(tools_module.save_agent_bundle, name="draft1", bundle=ok)
        assert saved["kind"] == "declarative" and saved["version"] == 1 and "error_code" not in saved
        bad = await _call(tools_module.save_agent_bundle, name="draft2",
                          bundle={"definition": {"bot_class": "NotAllowedClass"}})
        assert bad["error_code"] == "bot_class_not_allowed"
        invalid = await _call(tools_module.save_agent_bundle, name="draft3", bundle={"definition": {"bogus": 1}})
        assert invalid["error_code"] == "validation_error"
    assert await services.drafts.get(StudioPartition("t1"), "draft1") is not None
    assert await services.drafts.get(StudioPartition("t1"), "draft2") is None
    assert await services.drafts.get(StudioPartition.GLOBAL, "draft1") is None
    with _ctx(app, user_id="u2", scope=T1):
        with pytest.raises(PermissionError):
            await _call(tools_module.save_agent_bundle, name="draft1", bundle=ok)
    with _ctx(app):
        with pytest.raises(ValueError):
            await _call(tools_module.save_agent_bundle, name="BAD NAME", bundle=ok)
        with pytest.raises(ValueError):
            await _call(tools_module.save_agent_bundle, name="x", bundle={**ok, "name": "y"})


async def test_filesystem_mode_keeps_legacy_path(tmp_path, monkeypatch):
    app = web.Application()
    with _ctx(app):
        assert await tools_module._studio_partition_and_services(app) is None
        res = await _call(tools_module.save_agent_bundle, name="x", bundle={})
    assert res["error_code"] == "studio_storage_unavailable"


async def test_handler_assistant_gets_tenant_toolset(aiohttp_client, pool, monkeypatch):  # noqa: F811
    from parrot.handlers.studio.meta_agent import StudioAssistantHandler

    client = await aiohttp_client(_app(pool))
    handler = StudioAssistantHandler(make_mocked_request("POST", "/assistant", app=client.app))

    async def _tenant():
        return StudioPartition("t1")

    monkeypatch.setattr(handler, "_studio_partition", _tenant, raising=False)
    agent = await handler._get_or_create_assistant(None, api_key="sk-ant-offline")
    names = _names(agent.agent_tools())
    assert "save_agent_bundle" in names and "save_agent_draft" not in names
