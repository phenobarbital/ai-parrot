"""FEAT-605 M7 — drafts on the tenant path (real resolver, real ``SessionData``, real Postgres, routed requests)."""
from __future__ import annotations

import pytest

from parrot.handlers.studio import drafts as drafts_module
from parrot.handlers.studio.storage.models import StudioPartition
from parrot.registry.registry import AgentRegistry
from parrot.tools import tooling_policy
from parrot.tools.tooling_policy import TenantToolingPolicy

from .test_agents_db_mode import BASE, _offline, pool  # noqa: F401  (fixtures)
from .test_agents_visibility import tenant_app, who

PY_SOURCE = "from parrot.bots.basic import BasicBot\n\n\nclass Draft1(BasicBot):\n    pass\n"


@pytest.fixture(autouse=True)
def _drafts_dir(monkeypatch, tmp_path):
    """``AGENTS_DIR`` of the drafts package inside ``tmp_path``: any legacy write would show up there."""
    monkeypatch.setattr(drafts_module, "AGENTS_DIR", tmp_path / "agents")


def _app(pool):  # noqa: F811
    app = tenant_app(pool)
    return app


def _bundle(name, **extra):
    return {"name": name, "definition": {"bot_class": "BasicBot", "description": "d"}, **extra}


async def save(client, name, caller, **extra):
    """POST /drafts with a declarative bundle; ``bundle_extra`` goes into the bundle, the rest into the body."""
    bundle_extra = extra.pop("bundle_extra", {})
    resp = await client.post(f"{BASE}/drafts", json={"name": name, "bundle": _bundle(name, **bundle_extra), **extra},
                             headers=caller)
    return resp, await resp.json()


async def activate(client, name, caller, **body):
    resp = await client.post(f"{BASE}/drafts/{name}/activate", json=body, headers=caller)
    return resp, await resp.json()


async def draft_names(client, caller) -> set[str]:
    resp = await client.get(f"{BASE}/drafts", headers=caller)
    assert resp.status == 200, await resp.text()
    return {d["name"] for d in (await resp.json())["drafts"]}


async def test_list_get_filter_and_fields(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    owner = who("u1", groups="g1")
    assert (await save(client, "d-private", owner))[0].status == 201
    assert (await save(client, "d-tenant", owner, visibility="tenant"))[0].status == 201
    assert (await save(client, "d-groups", owner, visibility="groups", allowed_groups=["g1"]))[0].status == 201
    assert (await save(client, "d-other", who("u9", "globex")))[0].status == 201
    assert await draft_names(client, owner) == {"d-private", "d-tenant", "d-groups"}
    assert await draft_names(client, who("u2")) == {"d-tenant"}
    assert await draft_names(client, who("u3", groups="g1")) == {"d-tenant", "d-groups"}
    assert await draft_names(client, who("u4", admin=True)) == {"d-private", "d-tenant", "d-groups"}
    assert await draft_names(client, who("u5", superuser=True)) == {"d-private", "d-tenant", "d-groups"}
    assert await draft_names(client, who("u9", "globex")) == {"d-other"}
    assert await draft_names(client, who("u9", None)) == set()
    hidden = await client.get(f"{BASE}/drafts/d-private", headers=who("u2"))
    absent = await client.get(f"{BASE}/drafts/d-nothing", headers=who("u2"))
    assert hidden.status == absent.status == 404
    assert (await hidden.json())["message"].replace("d-private", "X") == (await absent.json())["message"].replace(
        "d-nothing", "X")
    body = await (await client.get(f"{BASE}/drafts/d-groups", headers=who("u3", groups="g1"))).json()
    assert {k: body[k] for k in ("tenant", "visibility", "allowed_groups", "access", "can_manage")} == {
        "tenant": "acme", "visibility": "groups", "allowed_groups": ["g1"], "access": "groups", "can_manage": False}
    assert body["owner"] == "u1"


async def test_python_source_is_declarative_only_on_the_tenant_path(aiohttp_client, pool, tmp_path):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    resp = await client.post(f"{BASE}/drafts", json={"name": "py", "source": PY_SOURCE}, headers=who("u1"))
    assert resp.status == 422 and (await resp.json())["code"] == "declarative_only"
    assert not (tmp_path / "agents" / "_drafts").exists()   # nothing was written to disk
    resp = await client.post(f"{BASE}/drafts", json={"name": "py", "source": PY_SOURCE}, headers=who("u1", author=False))
    assert resp.status == 403 and (await resp.json())["code"] == "authoring_denied"


async def test_save_rules(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    resp, body = await save(client, "x", who("u1", author=False))
    assert resp.status == 403 and body["code"] == "authoring_denied"
    resp, body = await save(client, "x", who("u1"), visibility="groups")
    assert resp.status == 422 and body["code"] == "groups_required"
    resp, body = await save(client, "x", who("u1", groups="g1"), visibility="groups", allowed_groups=["g2"])
    assert resp.status == 422 and body["code"] == "groups_not_allowed"
    resp, body = await save(client, "x", who("u1", None), visibility="tenant")
    assert resp.status == 422 and body["code"] == "tenant_required"
    for key in ("owner", "created_by", "tenant", "visibility", "allowed_groups"):
        resp, body = await save(client, "x", who("u1"), bundle_extra={"definition": {
            "bot_class": "BasicBot", "config": {key: "evil"}}})
        assert resp.status == 400 and body["code"] == "reserved_config_key", (key, body)
    assert await draft_names(client, who("u1")) == set()
    resp, body = await save(client, "ok", who("u4", admin=True), visibility="groups", allowed_groups=["g7"])
    assert resp.status == 201, body   # a tenant admin is not bound to its own groups


async def test_name_taken_before_anything_is_written(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    assert (await save(client, "shared", who("u1"), visibility="tenant"))[0].status == 201
    resp, body = await save(client, "shared", who("u2"))             # visible, not manageable
    assert resp.status == 409 and body["code"] == "name_taken" and "u1" not in body["message"]
    resp, body = await save(client, "shared", who("u3"), visibility="tenant")
    assert resp.status == 409 and body["code"] == "name_taken"
    stored = await client.app["studio_storage"].services.drafts.get(StudioPartition("acme"), "shared")
    assert stored.owner == "u1" and stored.version == 1
    resp, _ = await save(client, "shared", who("u1"), visibility="tenant")         # the owner updates
    assert resp.status == 201
    resp, _ = await save(client, "shared", who("u4", admin=True))                  # a tenant admin may as well
    assert resp.status == 201
    resp, _ = await save(client, "shared", who("u9", "globex"))                    # another tenant: its own name
    assert resp.status == 201


async def test_activation_imports_nothing_and_stamps_the_draft(aiohttp_client, pool, tmp_path, monkeypatch):  # noqa: F811
    def boom(*a, **k):
        raise AssertionError("the tenant path must never import a module")

    monkeypatch.setattr(AgentRegistry, "_import_module_from_path", boom)
    client = await aiohttp_client(_app(pool))
    assert (await save(client, "alpha", who("u1", groups="g1"), visibility="groups", allowed_groups=["g1"]))[0].status == 201
    resp, body = await activate(client, "alpha", who("u4", admin=True))      # an admin activates the owner's draft
    assert resp.status == 200, body
    assert body["activated"] is True and body["file_path"] is None
    agent = await client.app["studio_storage"].services.agents.get(StudioPartition("acme"), "alpha")
    assert (agent.owner, agent.tenant, agent.visibility, agent.allowed_groups) == ("u1", "acme", "groups", ("g1",))
    assert not list((tmp_path / "agents").rglob("*.py"))                       # AGENTS_DIR untouched
    assert client.app["bot_manager"].registry.has("alpha") is False            # nothing registered at activation


async def test_activation_replace_rules(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    created = await client.post(f"{BASE}/agents", json={"name": "alpha", "bot_class": "BasicBot"}, headers=who("u1"))
    assert created.status == 201
    assert (await save(client, "alpha", who("u1")))[0].status == 201
    resp, body = await activate(client, "alpha", who("u1"))                    # row present, replace=false
    assert resp.status == 409 and body["code"] == "name_taken"
    # a draft by u2 over u1's agent: not manageable even with replace=true -> name_taken, no disclosure
    assert (await save(client, "beta", who("u2")))[0].status == 201
    own = await client.post(f"{BASE}/agents", json={"name": "beta", "bot_class": "BasicBot"}, headers=who("u1"))
    assert own.status == 201
    resp, body = await activate(client, "beta", who("u2"), replace=True)
    assert resp.status == 409 and body["code"] == "name_taken"
    resp, body = await activate(client, "alpha", who("u1"), replace=True)      # owner of both: replace
    assert resp.status == 200 and body["version"] >= 2
    resp, body = await activate(client, "alpha", who("u1"), replace=True)      # already activated
    assert resp.status == 409


async def test_activate_gate_order(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    assert (await save(client, "mine", who("u1")))[0].status == 201
    assert (await save(client, "shared", who("u1"), visibility="tenant"))[0].status == 201
    assert (await activate(client, "mine", who("u2")))[0].status == 404          # invisible
    assert (await activate(client, "nothing", who("u2")))[0].status == 404
    assert (await activate(client, "mine", who("u2", author=False)))[0].status == 404   # still 404, not 403
    assert (await activate(client, "shared", who("u2")))[0].status == 403         # visible, not manageable
    resp, body = await activate(client, "shared", who("u1", author=False))        # manageable, may not author
    assert resp.status == 403 and body["code"] == "authoring_denied"
    assert (await activate(client, "shared", who("u1")))[0].status == 200


async def test_tooling_policy_at_save_and_at_activation(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    mcp = {"mcp_servers": [{"name": "s", "url": "https://m.example.com/mcp"}]}
    client.app[tooling_policy._POLICY_KEY] = (TenantToolingPolicy.deny_all())
    resp, body = await save(client, "t1", who("u1"), bundle_extra=mcp)
    assert resp.status == 422 and body["code"] == "tooling_not_permitted"
    assert await draft_names(client, who("u1")) == set()                          # refused before persistence
    client.app[tooling_policy._POLICY_KEY] = (TenantToolingPolicy(mcp_endpoints=("https://m.example.com/",)))
    assert (await save(client, "t1", who("u1"), bundle_extra=mcp))[0].status == 201
    client.app[tooling_policy._POLICY_KEY] = (TenantToolingPolicy.deny_all())         # the policy tightened since the save
    resp, body = await activate(client, "t1", who("u1"))
    assert resp.status == 422 and body["code"] == "tooling_not_permitted"
    assert await client.app["studio_storage"].services.agents.get(StudioPartition("acme"), "t1") is None


async def test_delete_gate(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    assert (await save(client, "mine", who("u1")))[0].status == 201
    assert (await save(client, "shared", who("u1"), visibility="tenant"))[0].status == 201
    assert (await client.delete(f"{BASE}/drafts/mine", headers=who("u2"))).status == 404
    assert (await client.delete(f"{BASE}/drafts/shared", headers=who("u2"))).status == 403
    assert (await client.delete(f"{BASE}/drafts/shared", headers=who("u1"))).status == 200


async def test_visibility_patch_rules(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(_app(pool))
    assert (await save(client, "mine", who("u1", groups="g1")))[0].status == 201
    assert (await save(client, "shared", who("u1"), visibility="tenant"))[0].status == 201
    url = lambda name: f"{BASE}/drafts/{name}/visibility"  # noqa: E731
    body = {"visibility": "tenant"}
    assert (await client.patch(url("mine"), json=body, headers=who("u2"))).status == 404
    assert (await client.patch(url("nothing"), json=body, headers=who("u2"))).status == 404
    assert (await client.patch(url("shared"), json=body, headers=who("u2"))).status == 403
    resp = await client.patch(url("mine"), json=body, headers=who("u1"))
    assert resp.status == 200 and (await resp.json())["visibility"] == "tenant"
    assert await draft_names(client, who("u2")) == {"mine", "shared"}
    resp = await client.patch(url("mine"), json={"visibility": "groups"}, headers=who("u1"))
    assert resp.status == 422 and (await resp.json())["code"] == "groups_required"
    resp = await client.patch(url("mine"), json={"visibility": "groups", "allowed_groups": ["g2"]},
                              headers=who("u1", groups="g1"))
    assert resp.status == 422 and (await resp.json())["code"] == "groups_not_allowed"
    resp = await client.patch(url("mine"), json={"visibility": "private"}, headers=who("u4", admin=True))
    assert resp.status == 200 and await draft_names(client, who("u2")) == {"shared"}
    resp = await client.patch(url("mine"), json={"visibility": "tenant"}, headers=who("u1", None))
    assert resp.status == 422 and (await resp.json())["code"] == "tenant_required"


async def test_plain_host_legacy_python_draft_carries_global_access(aiohttp_client, pool):  # noqa: F811
    """AC3: with no resolver a Python draft keeps its FEAT-467 shape plus the additive visibility fields."""
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE navigator.studio_drafts")
    try:
        plain = await aiohttp_client(tenant_app(pool, resolver=False))
        resp = await plain.post(f"{BASE}/drafts", json={"name": "pydraft", "source": PY_SOURCE},
                                headers={"X-User": "u1"})
        assert resp.status == 201, await resp.text()
        items = (await (await plain.get(f"{BASE}/drafts", headers={"X-User": "u1"})).json())["drafts"]
        legacy = next(i for i in items if i["name"] == "pydraft")
        assert legacy["kind"] == "python" and legacy["access"] == "global" and legacy["can_manage"] is True
        one = await (await plain.get(f"{BASE}/drafts/pydraft", headers={"X-User": "u2"})).json()
        assert one["access"] == "global" and one["can_manage"] is False and one["source"]
    finally:
        async with pool.acquire() as conn:
            await conn.execute("TRUNCATE navigator.studio_drafts")
