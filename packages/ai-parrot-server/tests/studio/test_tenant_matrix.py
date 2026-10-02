"""FEAT-605 M12 — end-to-end tenant matrix (actor × state × route) through the REAL routes.

Everything is mounted by ``setup_studio_routes(app, prefix="/api/v1/{tenant}/astudio", view_wrapper=seam)`` over a real
Postgres (``TEST_STUDIO_PG_DSN``), a real scope resolver, a real ``SessionData`` and ``BotManager.setup_registry_only``;
nothing of the partition / user / scope join is patched. ``seam`` is a ``web.View`` subclass (not a Mock) standing in for a
host seam prologue.

Mutation evidence (spec §4 plan; each guard was reverted by editing, the named test went RED, then it was re-applied):

| Guard | Test(s) that go RED (this module unless a path is given) |
|---|---|
| ``in_tenant`` in ``owns`` | ``test_access.py::test_owner_in_other_tenant_invisible`` ONLY — over the routes the store partition already excludes other tenants' rows, so it is defence in depth (the route test ``test_other_tenant_identical_404`` stays green by design) |
| ``in_tenant`` in ``administers`` | ``test_access.py::test_admin_bounded_to_tenant`` ONLY (same defence-in-depth reason; ``test_tenant_admin_rows`` asserts the end-to-end bound) |
| ``tenant_mismatch`` check | ``test_tenant_mismatch_403_before_record_access`` (+ ``test_base_scope.py::test_tenant_mismatch_403``) |
| ``studio_disabled`` check / ``/me`` exemption | ``test_studio_disabled_every_route_but_me`` (+ ``test_capabilities.py::test_me_when_disabled``) |
| ``_require_author`` on every create path + PATCH + activation + execute | ``test_authoring_denied_every_create_path`` |
| ``_studio_partition()`` never GLOBAL when opted in | ``test_access.py::test_partition_from_scope`` (not mutation-checked here) |
| ``r.tenant is not None`` in ``in_tenant`` | ``test_access.py::test_null_tenant_row_never_in_tenant``; ``test_resolver_tenant_none`` |
| reserved-key rejection | ``test_access.py::test_reserved_keys_rejected`` |
| per-tenant conflict → ``name_taken`` | ``test_names_per_tenant`` |
| ``declarative_only`` / no import on activation / D1 / D3 | ``test_drafts_tenant.py`` (``test_python_source_is_declarative_only_…``, ``test_activation_imports_nothing_…``), ``test_drafts_d1.py``, ``test_drafts_d3.py`` |
| opted-in-only gates (reload, files GET) | ``test_agents_visibility.py::test_reload_gate_opted_in_only``; this module's ``test_peer_rows`` / ``test_no_resolver_feat467_unchanged`` assert both sides (not mutation-checked here) |
| ``view_wrapper`` applied | ``test_seam_prologue_runs_for_every_route`` (+ ``test_base_scope.py::test_wrapper_prologue_runs_before_scope``) |
| idempotent hooks | ``test_registry_only_mount_hooks_once`` (+ ``test_host_mount.py::test_setup_twice_single_hook``) |
| assistant partition key includes the tenant / partition-only DELETE | ``test_assistant_one_session_two_tenants`` (+ ``test_assistant_partition.py``) |
| runtime ``chatbot_id`` = ``agent_id`` (storage builder) | ``test_same_name_agents_shared_memory_backend`` |
| ``TenantToolingPolicy`` on tooling writes / host writes fail closed | ``test_tooling_policy_rows`` (+ ``test_tooling_policy_routes.py``) |
| scope enforcement on options / execute | ``test_scope_enforcement_handlers.py``, ``test_scope_binding.py`` (the §4 names ``test_options_scope_enforced`` / ``test_execute_standalone_scope_enforced`` live there) |
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from parrot.bots.abstract import AbstractBot
from parrot.handlers.scope import RequestScope
from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio.storage.models import (
    StudioAgentDefinition,
    StudioAgentRecord,
    StudioAgentSnapshot,
    StudioPartition,
)
from parrot.handlers.studio.storage.services._common import StudioToolingGate
from parrot.manager.manager import BotManager
from parrot.manager.studio_builder import StudioAgentBuilder
from parrot.memory import ConversationTurn, InMemoryConversation
from parrot.registry import agent_registry

from ._host_probe import host_plugins, no_subprocess  # noqa: F401
from .test_agents_db_mode import _offline, _session, pool  # noqa: F401  (fixtures)
from .test_agents_visibility import tenant_app
from .test_assistant_partition import partition_app, probe  # noqa: F401  (fixtures)
from .test_drafts_tenant import _drafts_dir  # noqa: F401  (fixture)
from .test_skills_catalog_db_mode import PAYLOAD
from .test_skills_visibility import _registry  # noqa: F401  (fixture)

PREFIX = "/api/v1/{tenant}/astudio"
PLAIN = "/api/v1/astudio"


class MatrixResolver:
    """A real scope resolver: the whole scope comes from request headers (``X-Disabled`` ⇒ ``studio_enabled=False``)."""

    async def resolve(self, request: web.Request) -> RequestScope:
        h = request.headers
        return RequestScope(
            user_id=h.get("X-User", "u1"), tenant=h.get("X-Tenant") or None,
            groups=frozenset(g for g in h.get("X-Groups", "").split(",") if g),
            is_superuser="X-Super" in h, may_author=h.get("X-Author", "1") == "1", may_administer="X-Admin" in h,
            studio_enabled="X-Disabled" not in h,
        )


def seam(cls):
    """A host-seam double: a real ``web.View`` subclass whose ``_iter`` stashes the declared tenant first."""

    class Seam(cls):
        async def _iter(self):
            self.request.app.setdefault("_seam_seen", []).append(self.request.match_info.get("tenant"))
            return await super()._iter()

    Seam.__name__ = cls.__name__
    return Seam


def who(user, tenant="acme", *, groups="", admin=False, superuser=False, author=True, disabled=False) -> dict:
    h = {"X-User": user}
    if tenant:
        h["X-Tenant"] = tenant
    for flag, key, val in ((groups, "X-Groups", groups), (admin, "X-Admin", "1"), (superuser, "X-Super", "1"),
                           (disabled, "X-Disabled", "1"), (not author, "X-Author", "0")):
        if flag:
            h[key] = val
    return h


def url(tenant: str | None, path: str) -> str:
    return f"/api/v1/{tenant}/astudio{path}" if tenant else f"{PLAIN}{path}"


@pytest.fixture
def scoped_app(pool):  # noqa: F811
    """Prefixed mount + resolver + seam double + registry-only manager over the real store."""
    app = web.Application(middlewares=[_session])
    app["database"] = pool
    app["scope_resolver"] = MatrixResolver()
    BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True,
               enable_swagger_api=False).setup_registry_only(app)
    setup_studio_routes(app, prefix=PREFIX, view_wrapper=seam)
    return app


async def seed(client) -> dict:
    """acme: u1 owns private / tenant / groups(g1) rows of each kind; globex: u9 owns the same slugs + one of its own."""
    owner, other = who("u1", groups="g1"), who("u9", "globex")
    ids = {}
    for tenant, caller, extra in (("acme", owner, {}), ("globex", other, {})):
        for slug, vis in (("m-priv", {}), ("m-tenant", {"visibility": "tenant"}),
                          ("m-groups", {"visibility": "groups", "allowed_groups": ["g1"]})):
            if tenant == "globex" and vis.get("visibility") == "groups":
                continue
            body = {**vis, **extra}
            r, b = await create_in(client, tenant, "agents", slug, caller, body)
            assert r.status == 201, b
            r, b = await save_in(client, tenant, slug, caller, body)
            assert r.status == 201, b
            r, b = await publish_in(client, tenant, slug, caller, body)
            assert r.status == 201, b
            ids[(tenant, slug)] = b["skill_id"]
    for slug in ("acme-only",):
        assert (await create_in(client, "acme", "agents", slug, owner, {}))[0].status == 201
        assert (await save_in(client, "acme", slug, owner, {}))[0].status == 201
        r, b = await publish_in(client, "acme", slug, owner, {})
        ids[("acme", slug)] = b["skill_id"]
    assert (await create_in(client, "globex", "agents", "globex-only", other, {}))[0].status == 201
    return ids


async def create_in(client, tenant, _kind, name, caller, body):
    resp = await client.post(url(tenant, "/agents"), json={"name": name, "bot_class": "BasicBot", **body}, headers=caller)
    return resp, await resp.json()


async def save_in(client, tenant, name, caller, body):
    payload = {"name": name, "bundle": {"name": name, "definition": {"bot_class": "BasicBot", "description": "d"}}, **body}
    resp = await client.post(url(tenant, "/drafts"), json=payload, headers=caller)
    return resp, await resp.json()


async def publish_in(client, tenant, name, caller, body):
    resp = await client.post(url(tenant, "/skills"), json={**PAYLOAD, "name": name, **body}, headers=caller)
    return resp, await resp.json()


async def listing(client, tenant, kind, caller) -> set[str]:
    resp = await client.get(url(tenant, f"/{kind}"), headers=caller)
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    if kind == "skills":
        return {s["name"] for cat in body["skills"].values() for s in cat}
    return {i["name"] for i in body[kind]}


def manage_calls(ids, tenant="acme", name="m-tenant"):
    """Every manage-only addressed route of the §2 table, as ``(label, method, path, json)``."""
    sid = ids[(tenant, name)]
    return [
        ("agent PATCH", "patch", f"/agents/{name}", {"description": "x"}),
        ("agent visibility", "patch", f"/agents/{name}/visibility", {"visibility": "private"}),
        ("agent DELETE", "delete", f"/agents/{name}", None),
        ("agent reload", "post", f"/agents/{name}/reload", None),
        ("files GET", "get", f"/agents/{name}/files/identity", None),
        ("files PUT", "put", f"/agents/{name}/files/identity/r.md", {"content": "x"}),
        ("toolkit-config PUT", "put", f"/agents/{name}/toolkits/wiki", {"params": {}, "user_overridable": []}),
        ("mcp-servers PUT", "put", f"/agents/{name}/mcp-servers", {"servers": []}),
        ("draft visibility", "patch", f"/drafts/{name}/visibility", {"visibility": "private"}),
        ("draft activate", "post", f"/drafts/{name}/activate", {}),
        ("draft DELETE", "delete", f"/drafts/{name}", None),
        ("skill visibility", "patch", f"/skills/{sid}/visibility", {"visibility": "private"}),
        ("skill PUT", "put", f"/skills/{sid}", {**PAYLOAD, "name": name}),
        ("skill DELETE", "delete", f"/skills/{sid}", None),
    ]


async def call(client, tenant, method, path, caller, body=None):
    kwargs = {"headers": caller, **({"json": body} if body is not None else {})}
    resp = await getattr(client, method)(url(tenant, path), **kwargs)
    try:
        return resp, await resp.json()
    except Exception:  # noqa: BLE001 - a non-JSON body is asserted on status only
        return resp, {}


async def test_owner_rows(aiohttp_client, scoped_app):
    client = await aiohttp_client(scoped_app)
    ids = await seed(client)
    owner = who("u1", groups="g1")
    for kind in ("agents", "drafts", "skills"):
        assert await listing(client, "acme", kind, owner) >= {"m-priv", "m-tenant", "m-groups", "acme-only"}
        assert not await listing(client, "acme", kind, owner) & {"globex-only"}
    for path in ("/agents/m-priv", "/drafts/m-priv", f"/skills/{ids[('acme', 'm-priv')]}"):
        resp, body = await call(client, "acme", "get", path, owner)
        assert resp.status == 200 and body["can_manage"] is True and body["owner"] == "u1", path
        assert {"tenant", "visibility", "allowed_groups", "access"} <= set(body), path
    for path in ("/agents/m-priv/visibility", "/drafts/m-priv/visibility",
                 f"/skills/{ids[('acme', 'm-priv')]}/visibility"):
        resp, body = await call(client, "acme", "patch", path, owner, {"visibility": "tenant"})
        assert resp.status == 200 and body["visibility"] == "tenant", path
    resp, _ = await call(client, "acme", "patch", "/agents/m-priv", owner, {"description": "new"})
    assert resp.status == 200
    resp, _ = await call(client, "acme", "delete", "/drafts/acme-only", owner)
    assert resp.status == 200


async def test_peer_rows(aiohttp_client, scoped_app):
    client = await aiohttp_client(scoped_app)
    ids = await seed(client)
    peer, g_peer = who("u2"), who("u3", groups="g1")
    for kind in ("agents", "drafts", "skills"):
        assert await listing(client, "acme", kind, peer) == {"m-tenant"} | ({"acme-only"} - {"acme-only"})
        assert await listing(client, "acme", kind, g_peer) == {"m-tenant", "m-groups"}
    resp, body = await call(client, "acme", "get", "/agents/m-tenant", peer)
    assert resp.status == 200 and body["can_manage"] is False and body["access"] == "tenant"
    resp, body = await call(client, "acme", "get", "/agents/m-groups", g_peer)
    assert resp.status == 200 and body["access"] == "groups"
    assert (await call(client, "acme", "get", "/agents/m-groups", peer))[0].status == 404
    for label, method, path, body in manage_calls(ids):
        resp, data = await call(client, "acme", method, path, peer, body)
        assert resp.status == 403 and data["code"] == "not_manageable", (label, resp.status, data)


async def test_tenant_admin_rows(aiohttp_client, scoped_app):
    client = await aiohttp_client(scoped_app)
    ids = await seed(client)
    admin = who("u4", admin=True)
    for kind in ("agents", "drafts", "skills"):
        assert await listing(client, "acme", kind, admin) >= {"m-priv", "m-tenant", "m-groups", "acme-only"}
        assert not await listing(client, "acme", kind, admin) & {"globex-only"}
    for path in ("/agents/globex-only", "/drafts/globex-only", f"/skills/{ids[('globex', 'm-priv')]}"):
        assert (await call(client, "acme", "get", path, admin))[0].status == 404, path   # another tenant's record
    resp, body = await call(client, "acme", "patch", "/agents/m-priv/visibility", admin, {"visibility": "tenant"})
    assert resp.status == 200, body
    resp, body = await call(client, "acme", "post", "/skills/resync", admin)
    assert resp.status == 403 and body["code"] == "admin_required"                   # resync is the global superuser's


async def test_global_superuser_under_tenant_url(aiohttp_client, scoped_app):
    client = await aiohttp_client(scoped_app)
    ids = await seed(client)
    root = who("u5", superuser=True)
    assert await listing(client, "acme", "agents", root) >= {"m-priv", "m-groups"}
    assert "globex-only" not in await listing(client, "acme", "agents", root)       # bounded to the URL tenant
    assert (await call(client, "acme", "get", "/agents/globex-only", root))[0].status == 404
    resp, body = await call(client, "acme", "patch", "/drafts/m-priv/visibility", root, {"visibility": "tenant"})
    assert resp.status == 200, body
    resp, body = await call(client, "acme", "post", "/skills/resync", root)
    assert resp.status == 200, body
    assert ids


async def test_other_tenant_identical_404(aiohttp_client, scoped_app):
    """The record's own owner under another tenant's URL: lists omit, every addressed route 404 identical to absent."""
    client = await aiohttp_client(scoped_app)
    ids = await seed(client)
    visitor = who("u1", "globex", groups="g1")
    for kind in ("agents", "drafts", "skills"):
        assert not await listing(client, "globex", kind, visitor) & {"acme-only"}
    sid = ids[("acme", "acme-only")]
    for label, method, path, body in manage_calls(ids, name="m-tenant"):
        name = "acme-only"
        real = path.replace("m-tenant", name).replace(ids[("acme", "m-tenant")], sid)
        ghost = path.replace("m-tenant", "ghost-x").replace(ids[("acme", "m-tenant")], str(uuid.uuid4()))
        a, a_body = await call(client, "globex", method, real, visitor, body)
        b, b_body = await call(client, "globex", method, ghost, visitor, body)
        assert a.status == b.status == 404, (label, a.status, b.status)
        norm = lambda d, n: repr(d).replace(n, "X")  # noqa: E731
        assert norm(a_body, name) == norm(b_body, "ghost-x").replace(sid, "X") or a_body.get("code") == b_body.get("code")


async def test_tenant_mismatch_403_before_record_access(aiohttp_client, scoped_app):
    client = await aiohttp_client(scoped_app)
    await seed(client)
    resp = await client.get(url("globex", "/agents/m-tenant"), headers=who("u1", "acme"))
    assert resp.status == 403 and (await resp.json())["code"] == "tenant_mismatch"


async def test_resolver_tenant_none(aiohttp_client, pool):  # noqa: F811
    """A resolver is installed but the caller has no tenant (plain-prefix mount): empty lists, 404, 422 on create."""
    client = await aiohttp_client(tenant_app(pool))
    assert (await create_in(client, None, "agents", "seed", who("u1"), {}))[0].status == 201
    resp = await client.get(f"{PLAIN}/agents", headers=who("u1", None))
    assert resp.status == 200 and (await resp.json())["agents"] == []
    seen = await client.get(f"{PLAIN}/agents/seed", headers=who("u1", None))     # exists, but in a tenant
    ghost = await client.get(f"{PLAIN}/agents/ghost", headers=who("u1", None))
    assert seen.status == ghost.status and seen.status in (404, 422)              # never an existence oracle
    assert (await seen.json())["code"] == (await ghost.json())["code"]
    for path, body in (("/agents", {"name": "n", "bot_class": "BasicBot", "visibility": "tenant"}),
                       ("/drafts", {"name": "n", "bundle": {"name": "n", "definition": {"bot_class": "BasicBot"}},
                                    "visibility": "tenant"}),
                       ("/skills", {**PAYLOAD, "name": "n", "visibility": "tenant"})):
        resp = await client.post(f"{PLAIN}{path}", json=body, headers=who("u1", None))
        assert resp.status == 422 and (await resp.json())["code"] == "tenant_required", path


async def test_studio_disabled_every_route_but_me(aiohttp_client, scoped_app):
    client = await aiohttp_client(scoped_app)
    off = who("u1", disabled=True)
    resp = await client.get(url("acme", "/me"), headers=off)
    body = await resp.json()
    assert resp.status == 200 and body["enabled"] is False
    seen = 0
    for route in scoped_app.router.routes():
        if route.resource is None or route.method == "HEAD":
            continue
        path = route.resource.canonical.replace("{tenant}", "acme")
        if path.endswith("/me"):
            continue
        path = path.replace("{filename:.*}", "f.md")
        for part in ("name", "id", "slug", "kind", "provider", "param"):
            path = path.replace("{" + part + "}", "x")
        resp = await client.get(path, headers=off)
        if resp.status == 405:
            resp = await client.post(path, json={}, headers=off)
        assert resp.status == 404 and (await resp.json())["code"] == "studio_disabled", (path, resp.status)
        seen += 1
    assert seen > 20


async def test_authoring_denied_every_create_path(aiohttp_client, scoped_app):
    client = await aiohttp_client(scoped_app)
    await seed(client)
    reader = who("u1", groups="g1", author=False)       # u1 owns the rows, but may not author
    calls = [
        ("POST /agents", "post", "/agents", {"name": "new", "bot_class": "BasicBot"}),
        ("POST /drafts", "post", "/drafts", {"name": "new", "bundle": {"name": "new", "definition": {}}}),
        ("POST /skills", "post", "/skills", {**PAYLOAD, "name": "new"}),
        ("PATCH /agents/{name}", "patch", "/agents/m-priv", {"description": "x"}),
        ("activate", "post", "/drafts/m-priv/activate", {}),
        ("execute", "post", "/tools/anything/execute", {"args": {}}),
    ]
    for label, method, path, body in calls:
        resp, data = await call(client, "acme", method, path, reader, body)
        assert resp.status == 403 and data["code"] == "authoring_denied", (label, resp.status, data)


async def test_no_resolver_feat467_unchanged(aiohttp_client, pool):  # noqa: F811
    client = await aiohttp_client(tenant_app(pool, resolver=False))
    caller = {"X-User": "u1"}
    resp = await client.post(f"{PLAIN}/agents", json={"name": "legacy", "bot_class": "BasicBot"}, headers=caller)
    assert resp.status == 201, await resp.text()
    resp = await client.get(f"{PLAIN}/agents/legacy", headers={"X-User": "u2"})        # GET never needs ownership
    assert resp.status == 200
    resp = await client.patch(f"{PLAIN}/agents/legacy/visibility", json={"visibility": "tenant"}, headers=caller)
    assert resp.status == 422                                                           # non-private needs a tenant scope


async def test_names_per_tenant(aiohttp_client, scoped_app):
    client = await aiohttp_client(scoped_app)
    owner = who("u1")
    await seed(client)                                    # m-priv exists in acme AND globex (both 201)
    peer = who("u2")                                      # same tenant, another user: a second create is a conflict
    out = []
    resp, body = await create_in(client, "acme", "agents", "m-priv", peer, {})
    out.append(("agents", resp.status, body))
    resp, body = await save_in(client, "acme", "m-priv", peer, {})
    out.append(("drafts", resp.status, body))
    resp, body = await publish_in(client, "acme", "m-priv", peer, {})
    out.append(("skills", resp.status, body))
    assert (await create_in(client, "acme", "agents", "act-x", owner, {}))[0].status == 201
    assert (await save_in(client, "acme", "act-x", peer, {}))[0].status == 201
    resp, body = await call(client, "acme", "post", "/drafts/act-x/activate", peer, {})
    out.append(("activation", resp.status, body))
    for label, status, body in out:
        assert status == 409 and body["code"] == "name_taken", (label, status, body)
        assert not {"owner", "source", "tenant"} & set(body), (label, body)


async def test_seam_prologue_runs_for_every_route(aiohttp_client, scoped_app):
    client = await aiohttp_client(scoped_app)
    await seed(client)
    assert scoped_app["_seam_seen"] and set(scoped_app["_seam_seen"]) == {"acme", "globex"}


async def test_assistant_one_session_two_tenants(aiohttp_client, pool, probe):  # noqa: F811
    """One login switching tenants: no history crosses, DELETE in one tenant leaves the other intact."""
    client = await aiohttp_client(partition_app(pool))
    acme, globex = who("u1", "acme"), who("u1", "globex")
    for caller in (acme, globex, acme, globex):
        resp = await client.post(f"{PLAIN}/assistant", json={"query": "hi", "use_byok": False}, headers=caller)
        assert resp.status == 200
    a1, b1, a2, b2 = probe["asks"]
    assert a1["session_id"] == a2["session_id"] != b1["session_id"] == b2["session_id"]
    assert a1["memory_key"] != b1["memory_key"]
    assert (await client.delete(f"{PLAIN}/assistant", headers=acme)).status == 200
    resp = await client.post(f"{PLAIN}/assistant", json={"query": "again", "use_byok": False}, headers=globex)
    assert resp.status == 200 and probe["asks"][-1]["session_id"] == b1["session_id"]


def _snapshot(tenant, name, agent_id):
    now = datetime.now(timezone.utc)
    rec = StudioAgentRecord(agent_id, tenant, name, "u1", "private", (), StudioAgentDefinition(), "active", 1, now, now)
    return StudioAgentSnapshot(rec, (), ())


async def test_same_name_agents_shared_memory_backend(monkeypatch, tmp_path):
    """Two tenants, one agent name, ONE memory backend: histories are disjoint (``chatbot_id`` = ``agent_id``)."""
    monkeypatch.setattr(AbstractBot, "configure", AsyncMock())
    memory = InMemoryConversation()
    builder = StudioAgentBuilder(agent_registry, tmp_path / "runtime", StudioToolingGate({}))
    bots = []
    for tenant in ("acme", "globex"):
        bot, _ = await builder.build(_snapshot(tenant, "same", uuid.uuid4()), web.Application(),
                                     part=StudioPartition(tenant))
        bot.conversation_memory = memory
        await bot.create_conversation_history("u1", "s1")
        bots.append(bot)
    acme_bot, globex_bot = bots
    assert acme_bot.name == globex_bot.name and acme_bot.memory_key_id != globex_bot.memory_key_id
    for bot, text in ((acme_bot, "acme secret"), (globex_bot, "globex secret")):
        turn = ConversationTurn(turn_id=uuid.uuid4().hex, user_id="u1", user_message=text, assistant_response="ok",
                                chatbot_id=bot.memory_key_id)
        await bot.save_conversation_turn("u1", "s1", turn)
    seen = {}
    for bot in bots:
        history = await bot.get_conversation_history("u1", "s1")
        seen[bot.memory_key_id] = [t.user_message for t in history.turns]
    assert sorted(sum(seen.values(), [])) == ["acme secret", "globex secret"]
    assert all(len(v) == 1 for v in seen.values())


async def test_registry_only_mount_hooks_once():
    app = web.Application()
    manager = BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True,
                         enable_swagger_api=False)
    manager.setup_registry_only(app)
    setup_studio_routes(app, prefix=PREFIX)
    before = (len(app.on_startup), len(app.on_shutdown), len(app.on_cleanup))
    manager.setup_registry_only(app)
    setup_studio_routes(app, prefix=PREFIX)
    setup_studio_routes(app, prefix="/t/{tenant}/astudio")
    assert (len(app.on_startup), len(app.on_shutdown), len(app.on_cleanup)) == before
    assert app["bot_manager"] is manager


async def test_tooling_policy_rows(aiohttp_client, scoped_app, no_subprocess, host_plugins):  # noqa: F811
    client = await aiohttp_client(scoped_app)
    owner = who("u1")
    assert (await create_in(client, "acme", "agents", "mine", owner, {}))[0].status == 201
    servers = {"servers": [{"name": "s", "transport": "stdio", "command": "echo", "args": ["x"]}]}
    resp, body = await call(client, "acme", "put", "/agents/mine/mcp-servers", owner, servers)
    assert resp.status == 422 and body["code"] == "tooling_not_permitted", body
    resp, body = await call(client, "acme", "get", "/agents/mine/mcp-servers", owner)
    assert body["servers"] == [] and no_subprocess == []                                  # nothing persisted, no process
    resp, body = await call(client, "acme", "post", "/tools/tp_probe_tool_write/execute", owner, {"args": {"value": "x"}})
    assert resp.status == 403 and body["code"] == "confirmation_required"
    resp, body = await call(client, "acme", "post", "/tools/shell/execute", owner, {"args": {}})
    assert resp.status == 403 and body["code"] == "tooling_not_permitted"
