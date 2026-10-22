"""FEAT-605 M10 — meta-agent tools under a bound ``studio_scope`` (real scope, real Postgres, real RequestContext)."""
from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.bots.studio import tools as tools_module
from parrot.handlers.scope import RequestScope
from parrot.handlers.studio.access import build_tool_scope
from parrot.handlers.studio.storage.models import StudioAgentDefinition, StudioPartition
from parrot.utils.helpers import RequestContext, _current_ctx

from .test_agents_db_mode import _app, _offline, pool  # noqa: F401  (fixtures)
from .test_agents_visibility import tenant_app, who  # noqa: F401
from .test_assistant_tools_db_mode import _call

SKILL = dict(name="s1", description="x", category="general", triggers=["/s"],
             body="---\nname: s1\ndescription: x\n---\nbody")


def scope_of(user="u1", tenant="t1", *, author=True, admin=False, groups=()):
    return build_tool_scope(RequestScope(user_id=user, tenant=tenant, groups=frozenset(groups), may_author=author,
                                         may_administer=admin))


@contextlib.contextmanager
def ctx(app, scope=None, user_id="u1"):
    extra = {"studio_scope": scope} if scope is not None else {}
    token = _current_ctx.set(RequestContext(app=app, user_id=user_id, **extra))
    try:
        yield
    finally:
        _current_ctx.reset(token)


async def seed_agent(app, tenant, name, owner, visibility="private", groups=()):
    await app["studio_storage"].services.agents.create(
        StudioPartition(tenant), name=name, owner=owner, definition=StudioAgentDefinition(bot_class="BasicBot"),
        visibility=visibility, allowed_groups=groups)


async def test_tools_without_scope_unchanged(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    app = client.app
    from parrot.bots.basic import BasicBot

    registry = app["bot_manager"].registry
    registry.register("legacy-meta", BasicBot)
    try:
        with ctx(app):
            assert "legacy-meta" in await _call(tools_module.list_existing_agents)     # FEAT-467: the registry names
    finally:
        registry.unregister("legacy-meta")   # process-wide registry: never leak into other tests


MUTATING = [
    ("save_agent_draft", dict(name="d1", source="class A: pass")),
    ("save_agent_bundle", dict(name="d1", bundle={"definition": {"bot_class": "BasicBot"}})),
    ("create_yaml_agent", dict(name="a1", bot_class="BasicBot")),
    ("write_kb_file", dict(agent_name="a1", filename="n.md", content="c")),
    ("publish_skill_to_catalog", SKILL),
]


@pytest.mark.parametrize("tool_name,kwargs", MUTATING, ids=[m[0] for m in MUTATING])
async def test_authoring_denied_meta_tools(aiohttp_client, pool, tool_name, kwargs):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    app = client.app
    with ctx(app, scope_of(author=False)):
        with pytest.raises(PermissionError, match="authoring_denied"):
            await _call(getattr(tools_module, tool_name), **kwargs)
    services = app["studio_storage"].services
    part = StudioPartition("t1")
    assert await services.agents.list(part) == [] and await services.drafts.list(part) == []


async def test_save_agent_draft_python_refused_tenant_path(aiohttp_client, pool, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(tools_module, "AGENTS_DIR", tmp_path / "agents_dir")
    client = await aiohttp_client(_app(pool))
    with ctx(client.app, scope_of()):
        with pytest.raises(PermissionError, match="declarative_only"):
            await _call(tools_module.save_agent_draft, name="d1", source="class A: pass")
    assert not (tmp_path / "agents_dir").exists()                            # nothing was written to disk


async def test_list_existing_agents_filtered(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    app = client.app
    await seed_agent(app, "t1", "mine", "u1")
    await seed_agent(app, "t1", "shared", "u1", "tenant")
    await seed_agent(app, "t1", "grouped", "u1", "groups", ("g1",))
    await seed_agent(app, "t2", "other", "u9", "tenant")
    listing = lambda scope: _call(tools_module.list_existing_agents)  # noqa: E731
    with ctx(app, scope_of("u2")):
        assert sorted(await listing(None)) == ["shared"]
    with ctx(app, scope_of("u3", groups=("g1",))):
        assert sorted(await listing(None)) == ["grouped", "shared"]
    with ctx(app, scope_of("u1")):
        assert sorted(await listing(None)) == ["grouped", "mine", "shared"]
    with ctx(app, scope_of("u4", admin=True)):
        assert sorted(await listing(None)) == ["grouped", "mine", "shared"]
    with ctx(app, scope_of("u9", "t2")):
        assert await listing(None) == ["other"]


async def test_list_existing_agents_fails_closed_on_an_opted_in_host_without_scope(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    with ctx(client.app):
        assert await _call(tools_module.list_existing_agents) == []


async def test_publish_skill_stamps_user_and_names_are_per_tenant(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    app = client.app
    with ctx(app, scope_of("u1", "t1"), user_id="u1"):
        skill = await _call(tools_module.publish_skill_to_catalog, **SKILL)
        assert skill["owner"] == "u1" and skill["owner"] != "agent_studio"
        assert skill["tenant"] == "t1" and skill["visibility"] == "private"
        dup = await _call(tools_module.publish_skill_to_catalog, **SKILL)
        assert dup["error_code"] == "name_taken"
    with ctx(app, scope_of("u9", "t2"), user_id="u9"):                      # the same name in another tenant
        other = await _call(tools_module.publish_skill_to_catalog, **SKILL)
        assert other["tenant"] == "t2" and "error_code" not in other


async def test_asset_and_agent_tools_follow_the_access_rule(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    app = client.app
    await seed_agent(app, "t1", "alpha", "u1", "tenant")
    with ctx(app, scope_of("u2"), user_id="u2"):                              # visible, not manageable
        with pytest.raises(PermissionError):
            await _call(tools_module.write_kb_file, agent_name="alpha", filename="n.md", content="x")
    with ctx(app, scope_of("u4", admin=True), user_id="u4"):                  # a tenant admin manages
        res = await _call(tools_module.write_kb_file, agent_name="alpha", filename="n.md", content="x")
        assert res["size"] == 1
    with ctx(app, scope_of("u9", "t2"), user_id="u9"):                        # another tenant: not even a row
        with pytest.raises(ValueError):
            await _call(tools_module.write_kb_file, agent_name="alpha", filename="n.md", content="x")


async def test_require_agent_owner_other_tenant_refused():
    meta = SimpleNamespace(bot_config=SimpleNamespace(config={"created_by": "1"}))
    registry = SimpleNamespace(get_metadata=lambda name: meta)
    app = {"bot_manager": SimpleNamespace(registry=registry)}
    await tools_module._require_agent_owner(app, "myagent", "1")              # no scope: FEAT-467 behaviour
    with ctx(app, scope_of("1", "t1")):
        with pytest.raises(ValueError, match="not found"):                    # a tenant caller never reaches a tenant-less agent
            await tools_module._require_agent_owner(app, "myagent", "1")


async def test_assistant_binds_studio_scope(aiohttp_client, pool, monkeypatch):  # noqa: F811
    from parrot.handlers.studio import meta_agent

    seen = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            self.name = "fake-assistant"

        async def configure(self, app):
            return None

        @contextlib.asynccontextmanager
        async def session(self, **kwargs):
            seen.update(kwargs)
            yield SimpleNamespace(ask=AsyncMock(return_value=SimpleNamespace(content="hi", metadata={})))

    monkeypatch.setattr(meta_agent, "AgentStudioAgent", FakeAgent)
    client = await aiohttp_client(tenant_app(pool))
    resp = await client.post("/api/v1/astudio/assistant", json={"query": "hi", "use_byok": False}, headers=who("u1"))
    assert resp.status == 200, await resp.text()
    assert seen["studio_scope"].caller.tenant == "acme" and seen["studio_scope"].agent is None
    seen.clear()
    plain = await aiohttp_client(tenant_app(pool, resolver=False))
    resp = await plain.post("/api/v1/astudio/assistant", json={"query": "hi", "use_byok": False},
                            headers={"X-User": "u1"})
    assert resp.status == 200 and "studio_scope" not in seen                 # nothing bound without a resolver


async def test_legacy_publish_path_builds_its_glue_and_stamps_the_real_user(monkeypatch):
    """The legacy (non-database) publish used to die with ``AttributeError`` (read-only ``request`` on a handler)."""
    from parrot.handlers.studio.skills_catalog import SkillsCatalogGlue

    inserted: list = []

    async def _insert(self, entry):
        inserted.append(entry)

    monkeypatch.setattr(SkillsCatalogGlue, "_get_entry_by_name", AsyncMock(return_value=None))
    monkeypatch.setattr(SkillsCatalogGlue, "_insert_entry", _insert)
    registry_calls = []

    async def _dual(self, entry, owner):
        registry_calls.append(owner)
        return False

    monkeypatch.setattr(SkillsCatalogGlue, "_dual_write_to_registry", _dual)
    app = {"database": object()}
    with ctx(app, user_id="u7"):
        out = await _call(tools_module.publish_skill_to_catalog, **SKILL)
    assert out["owner"] == "u7" and out["name"] == "s1"
    assert inserted[0].owner == "u7" and registry_calls == ["u7"]                 # never "agent_studio"
    monkeypatch.setattr(SkillsCatalogGlue, "_get_entry_by_name", AsyncMock(return_value=object()))
    with ctx(app, user_id="u7"):
        with pytest.raises(ValueError, match="already exists"):
            await _call(tools_module.publish_skill_to_catalog, **SKILL)
    assert len(inserted) == 1
