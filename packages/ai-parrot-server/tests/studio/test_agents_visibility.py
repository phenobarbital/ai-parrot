"""FEAT-605 M6 — agents route matrix (aiohttp_client, real resolver, real ``SessionData``, real Postgres).

The caller is chosen by headers: ``X-User``, ``X-Tenant``, ``X-Groups`` (comma list), ``X-Admin`` (``may_administer``),
``X-Super`` (``is_superuser``), ``X-Author: 0`` (``may_author=False``). The scope resolver is a real
``ScopeResolver``-shaped object installed at ``app["scope_resolver"]``; nothing in the partition / user / scope join
is patched. ``AbstractBot.configure`` is replaced (autouse ``_offline``) so no LLM is started.
"""
from __future__ import annotations

from aiohttp import web

from parrot.bots.basic import BasicBot
from parrot.handlers.scope import RequestScope
from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio.agents import StudioAgentVisibilityHandler
from parrot.manager.manager import BotManager

from .test_agents_db_mode import BASE, _offline, _session, pool  # noqa: F401  (fixtures)


class HeaderResolver:
    """A real scope resolver: the whole scope comes from request headers."""

    async def resolve(self, request: web.Request) -> RequestScope:
        h = request.headers
        groups = frozenset(g for g in h.get("X-Groups", "").split(",") if g)
        return RequestScope(
            user_id=h.get("X-User", "u1"), tenant=h.get("X-Tenant") or None, groups=groups,
            is_superuser="X-Super" in h, may_author=h.get("X-Author", "1") == "1", may_administer="X-Admin" in h,
        )


def tenant_app(pool, *, resolver: bool = True) -> web.Application:  # noqa: F811
    """Registry-only Studio app; ``resolver=False`` is a plain host (no scope resolver installed)."""
    app = web.Application(middlewares=[_session])
    app["database"] = pool
    if resolver:
        app["scope_resolver"] = HeaderResolver()
    manager = BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True,
                         enable_swagger_api=False)
    manager.setup_registry_only(app)
    setup_studio_routes(app)
    app.router.add_view(f"{BASE}/agents/{{name}}/visibility", StudioAgentVisibilityHandler)
    return app


def who(user: str, tenant: str | None = "acme", *, groups: str = "", admin: bool = False, superuser: bool = False,
        author: bool = True) -> dict:
    """Request headers selecting the caller."""
    headers = {"X-User": user}
    if tenant:
        headers["X-Tenant"] = tenant
    if groups:
        headers["X-Groups"] = groups
    if admin:
        headers["X-Admin"] = "1"
    if superuser:
        headers["X-Super"] = "1"
    if not author:
        headers["X-Author"] = "0"
    return headers


async def create(client, name, caller, **extra):
    """POST /agents; returns ``(response, json body)``."""
    resp = await client.post(f"{BASE}/agents", json={"name": name, "bot_class": "BasicBot", **extra}, headers=caller)
    return resp, await resp.json()


async def seed(client):
    """acme: u1 owns a private, a tenant-visible and a groups(g1) agent; globex: u9 owns one."""
    owner = who("u1", groups="g1")
    assert (await create(client, "a-private", owner))[0].status == 201
    assert (await create(client, "a-tenant", owner, visibility="tenant"))[0].status == 201
    resp, body = await create(client, "a-groups", owner, visibility="groups", allowed_groups=["g1"])
    assert resp.status == 201, body
    assert (await create(client, "b-agent", who("u9", "globex")))[0].status == 201


async def names(client, caller) -> set[str]:
    resp = await client.get(f"{BASE}/agents", headers=caller)
    assert resp.status == 200, await resp.text()
    return {a["name"] for a in (await resp.json())["agents"]}


async def test_list_filters_by_access(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    assert await names(client, who("u1", groups="g1")) == {"a-private", "a-tenant", "a-groups"}      # owner
    assert await names(client, who("u2")) == {"a-tenant"}                                             # peer
    assert await names(client, who("u3", groups="g1")) == {"a-tenant", "a-groups"}                    # group member
    assert await names(client, who("u4", admin=True)) == {"a-private", "a-tenant", "a-groups"}        # tenant admin
    assert await names(client, who("u5", superuser=True)) == {"a-private", "a-tenant", "a-groups"}    # superuser: tenant only
    assert await names(client, who("u9", "globex")) == {"b-agent"}                                    # other tenant
    assert await names(client, who("u9", None)) == set()                                              # no tenant
    items = (await (await client.get(f"{BASE}/agents", headers=who("u2"))).json())["agents"]
    assert items[0]["access"] == "tenant" and items[0]["can_manage"] is False and items[0]["tenant"] == "acme"
    mine = {a["name"]: a for a in (await (await client.get(f"{BASE}/agents", headers=who("u1", groups="g1"))).json())["agents"]}
    assert mine["a-private"]["access"] == "owner" and mine["a-private"]["can_manage"] is True
    assert mine["a-groups"]["allowed_groups"] == ["g1"] and mine["a-groups"]["visibility"] == "groups"


async def test_get_invisible_identical_404(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    hidden = await client.get(f"{BASE}/agents/a-private", headers=who("u2"))
    absent = await client.get(f"{BASE}/agents/a-nothing", headers=who("u2"))
    other_tenant = await client.get(f"{BASE}/agents/b-agent", headers=who("u2"))
    assert hidden.status == absent.status == other_tenant.status == 404
    h, a = await hidden.json(), await absent.json()
    assert h["code"] == a["code"] == "not_found"
    assert h["message"].replace("a-private", "X") == a["message"].replace("a-nothing", "X")
    assert (await other_tenant.json())["message"].replace("b-agent", "X") == a["message"].replace("a-nothing", "X")


async def test_get_returns_visibility_fields(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    body = await (await client.get(f"{BASE}/agents/a-groups", headers=who("u3", groups="g1"))).json()
    assert {k: body[k] for k in ("tenant", "owner", "visibility", "allowed_groups", "access", "can_manage")} == {
        "tenant": "acme", "owner": "u1", "visibility": "groups", "allowed_groups": ["g1"], "access": "groups",
        "can_manage": False,
    }
    admin = await (await client.get(f"{BASE}/agents/a-private", headers=who("u4", admin=True))).json()
    assert admin["access"] == "admin" and admin["can_manage"] is True


async def test_authoring_denied_create_and_patch(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    resp, body = await create(client, "nope", who("u1", author=False))
    assert resp.status == 403 and body["code"] == "authoring_denied"
    resp = await client.patch(f"{BASE}/agents/a-private", json={"description": "x"}, headers=who("u1", author=False))
    assert resp.status == 403 and (await resp.json())["code"] == "authoring_denied"
    # order: an INVISIBLE agent is 404 even for a caller who may not author (no existence oracle)
    resp = await client.patch(f"{BASE}/agents/a-private", json={"description": "x"}, headers=who("u2", author=False))
    assert resp.status == 404
    absent = await client.patch(f"{BASE}/agents/a-nothing", json={"description": "x"}, headers=who("u2", author=False))
    assert absent.status == 404


async def test_patch_agent_policy_row(aiohttp_client, pool):  # noqa: F811
    """AC23: PATCH /agents/{name} answers 404 / 403 / authoring_denied, and 200 for the owner."""
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    patch = {"description": "edited"}
    assert (await client.patch(f"{BASE}/agents/a-private", json=patch, headers=who("u2"))).status == 404
    assert (await client.patch(f"{BASE}/agents/b-agent", json=patch, headers=who("u2"))).status == 404
    assert (await client.patch(f"{BASE}/agents/a-tenant", json=patch, headers=who("u2"))).status == 403
    assert (await client.patch(f"{BASE}/agents/a-tenant", json=patch, headers=who("u1", author=False))).status == 403
    resp = await client.patch(f"{BASE}/agents/a-tenant", json=patch, headers=who("u1"))
    assert resp.status == 200 and (await resp.json())["version"] == 2
    admin = await client.patch(f"{BASE}/agents/a-tenant", json=patch, headers=who("u4", admin=True))
    assert admin.status == 200
    for key in ("owner", "tenant", "visibility", "allowed_groups", "created_by"):
        resp = await client.patch(f"{BASE}/agents/a-tenant", json={key: "x"}, headers=who("u1"))
        assert resp.status == 400 and (await resp.json())["code"] == "reserved_config_key", key


async def test_reserved_keys_rejected_on_create(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    for key in ("owner", "created_by", "tenant", "visibility", "allowed_groups"):
        resp, body = await create(client, "reserved", who("u1"), config={key: "x"})
        assert resp.status == 400 and body["code"] == "reserved_config_key", (key, body)
    assert await names(client, who("u1")) == set()


async def test_create_stamps_server_owned_fields(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    resp, body = await create(client, "stamped", who("u1", groups="g1,g2"), visibility="groups",
                              allowed_groups=["g1"], owner="evil", tenant="globex")
    assert resp.status == 201 and body["tenant"] == "acme"
    item = await (await client.get(f"{BASE}/agents/stamped", headers=who("u1", groups="g1,g2"))).json()
    assert item["owner"] == "u1" and item["tenant"] == "acme" and item["allowed_groups"] == ["g1"]
    # 422 codes of the visibility rules
    resp, body = await create(client, "x1", who("u1"), visibility="groups")
    assert resp.status == 422 and body["code"] == "groups_required"
    resp, body = await create(client, "x2", who("u1", groups="g1"), visibility="groups", allowed_groups=["g2"])
    assert resp.status == 422 and body["code"] == "groups_not_allowed"
    resp, body = await create(client, "x3", who("u1", None), visibility="tenant")
    assert resp.status == 422 and body["code"] == "tenant_required"
    resp, body = await create(client, "x4", who("u4", admin=True), visibility="groups", allowed_groups=["g7"])
    assert resp.status == 201, body  # a tenant admin is not bound to its own groups


async def test_name_taken_only_inside_tenant(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    assert (await create(client, "shared", who("u1")))[0].status == 201
    resp, body = await create(client, "shared", who("u2"))
    assert resp.status == 409 and body["code"] == "name_taken"
    assert "u1" not in body["message"] and "acme" not in body["message"] and "studio" not in body["message"].lower()
    resp, _ = await create(client, "shared", who("u9", "globex"))
    assert resp.status == 201  # same slug in another tenant


async def test_delete_gate(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    assert (await client.delete(f"{BASE}/agents/a-private", headers=who("u2"))).status == 404
    assert (await client.delete(f"{BASE}/agents/a-tenant", headers=who("u2"))).status == 403
    assert (await client.delete(f"{BASE}/agents/a-tenant", headers=who("u1"))).status == 200


async def test_reload_gate_opted_in_only(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    reload_ = lambda name, caller: client.post(f"{BASE}/agents/{name}/reload", headers=caller)  # noqa: E731
    assert (await reload_("a-private", who("u2"))).status == 404
    assert (await reload_("a-nothing", who("u2"))).status == 404
    assert (await reload_("a-tenant", who("u2"))).status == 403     # visible, not manageable
    owner = await reload_("a-tenant", who("u1"))
    assert owner.status == 200, await owner.text()
    # a plain host (no resolver) keeps the ungated FEAT-467 reload: any caller may reload (G9)
    plain = await aiohttp_client(tenant_app(pool, resolver=False))
    resp, _ = await create(plain, "plain", {"X-User": "u1"})
    assert resp.status == 201
    other = await plain.post(f"{BASE}/agents/plain/reload", headers={"X-User": "u2"})
    assert other.status == 200, await other.text()


async def test_visibility_patch_rules(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool))
    await seed(client)
    url = lambda name: f"{BASE}/agents/{name}/visibility"  # noqa: E731
    body = {"visibility": "tenant", "allowed_groups": []}
    assert (await client.patch(url("a-private"), json=body, headers=who("u2"))).status == 404      # invisible
    assert (await client.patch(url("a-nothing"), json=body, headers=who("u2"))).status == 404
    assert (await client.patch(url("a-tenant"), json=body, headers=who("u2"))).status == 403       # visible only
    resp = await client.patch(url("a-private"), json=body, headers=who("u1"))
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["visibility"] == "tenant" and (await resp.json())["version"] >= 1
    assert await names(client, who("u2")) >= {"a-private", "a-tenant"}                              # now visible
    resp = await client.patch(url("a-private"), json={"visibility": "groups"}, headers=who("u1", groups="g1"))
    assert resp.status == 422 and (await resp.json())["code"] == "groups_required"
    resp = await client.patch(url("a-private"), json={"visibility": "groups", "allowed_groups": ["g2"]},
                              headers=who("u1", groups="g1"))
    assert resp.status == 422 and (await resp.json())["code"] == "groups_not_allowed"
    resp = await client.patch(url("a-private"), json={"visibility": "groups", "allowed_groups": ["g1"]},
                              headers=who("u1", groups="g1"))
    assert resp.status == 200 and (await resp.json())["allowed_groups"] == ["g1"]
    resp = await client.patch(url("a-private"), json={"visibility": "private"}, headers=who("u4", admin=True))
    assert resp.status == 200 and await names(client, who("u2")) == {"a-tenant"}                    # admin may manage
    assert (await client.patch(url("a-private"), json={"visibility": "nope"}, headers=who("u1"))).status == 400
    resp = await client.patch(url("a-private"), json={"visibility": "tenant"}, headers=who("u1", None))
    assert resp.status == 422 and (await resp.json())["code"] == "tenant_required"


async def test_visibility_patch_plain_host_needs_tenant(aiohttp_client, pool):  # noqa: F811
    plain = await aiohttp_client(tenant_app(pool, resolver=False))
    assert (await create(plain, "plain", {"X-User": "u1"}))[0].status == 201
    resp = await plain.patch(f"{BASE}/agents/plain/visibility", json={"visibility": "tenant"}, headers={"X-User": "u1"})
    assert resp.status == 422 and (await resp.json())["code"] == "tenant_required"
    resp, body = await create(plain, "plain2", {"X-User": "u1"}, visibility="tenant")
    assert resp.status == 422 and body["code"] == "tenant_required"


async def test_plain_host_items_carry_global_access(aiohttp_client, pool):  # noqa: F811
    """AC3: without a resolver the lists/items are unchanged plus the additive visibility fields."""
    plain = await aiohttp_client(tenant_app(pool, resolver=False))
    assert (await create(plain, "plain", {"X-User": "u1"}))[0].status == 201
    items = (await (await plain.get(f"{BASE}/agents", headers={"X-User": "u1"})).json())["agents"]
    assert items and all(i["access"] == "global" and i["visibility"] == "private" for i in items)
    one = await (await plain.get(f"{BASE}/agents/plain", headers={"X-User": "u2"})).json()
    assert one["access"] == "global" and one["can_manage"] is False
    # a legacy (registry) agent keeps its FEAT-467 shape plus the additive fields, in the list and by name
    plain.app["bot_manager"].registry.register("legacy-one", BasicBot)
    listing = (await (await plain.get(f"{BASE}/agents", headers={"X-User": "u1"})).json())["agents"]
    legacy = next(i for i in listing if i["name"] == "legacy-one")
    assert legacy["source"] == "registry" and legacy["access"] == "global" and legacy["visibility"] == "private"
    assert legacy["tenant"] is None and legacy["allowed_groups"] == []
    single = await (await plain.get(f"{BASE}/agents/legacy-one", headers={"X-User": "u1"})).json()
    assert single["access"] == "global" and "can_manage" in single
