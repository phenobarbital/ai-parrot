"""FEAT-621 W3 drafts in database mode (AC8, AC15, AC16).

Real aiohttp app, the real Studio routes, a session middleware installing a real ``SessionData`` and a real
Postgres pool. ``AbstractBot.configure`` is replaced so no LLM is ever started.
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from asyncdb import AsyncPool
from navigator_session.data import SessionData

from parrot.bots.abstract import AbstractBot
from parrot.handlers.studio import agents as agents_module
from parrot.handlers.studio import drafts as drafts_module
from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio.drafts import StudioDraftActivateHandler, StudioDraftsHandler
from parrot.handlers.studio.storage.migrate import apply_studio_migrations
from parrot.handlers.scope import RequestScope
from parrot.handlers.studio.storage.models import StudioAgentBundle, StudioAgentDefinition, StudioPartition
from parrot.manager.manager import BotManager
from parrot.registry import registry as registry_module

BASE = "/api/v1/astudio"
TABLES = ("ai_agent_assets", "ai_agent_tooling", "ai_agent_drafts", "ai_agents", "ai_skills_catalog")
PY_SOURCE = "from parrot.bots.basic import BasicBot\n\n\nclass Draft1(BasicBot):\n    pass\n"


@pytest.fixture
async def pool():
    dsn = os.environ.get("TEST_STUDIO_PG_DSN")
    if not dsn:
        pytest.skip("TEST_STUDIO_PG_DSN not set; Studio handler integration tests need Postgres")
    pg = AsyncPool("pg", dsn=dsn)
    await pg.connect()
    await apply_studio_migrations(pg)
    async with pg.acquire() as conn:
        for table in TABLES:
            await conn.execute(f"TRUNCATE navigator.{table} CASCADE")
        await conn.execute("TRUNCATE navigator.studio_drafts")
    yield pg
    async with pg.acquire() as conn:
        for table in TABLES:
            await conn.execute(f"TRUNCATE navigator.{table} CASCADE")
        await conn.execute("TRUNCATE navigator.studio_drafts")
    await pg.close()


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    monkeypatch.setattr(AbstractBot, "configure", AsyncMock())
    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("STUDIO_SWEEP_INTERVAL_SECONDS", "3600")
    monkeypatch.setattr(agents_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(drafts_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path / "agents")


@web.middleware
async def _session(request, handler):
    user = request.headers.get("X-User", "u1")
    request["NAV_SESSION"] = SessionData(data={"session": {"user_id": user, "groups": [], "superuser": False}})
    request["authenticated"] = True
    return await handler(request)


class _AcmeDrafts(StudioDraftsHandler):
    async def _studio_partition(self):
        return StudioPartition("acme")

    async def _scope(self):  # the partition and the scope agree on the tenant (as an opted-in host would)
        return RequestScope(user_id=None, tenant="acme", groups=frozenset())


class _AcmeActivate(StudioDraftActivateHandler):
    async def _studio_partition(self):
        return StudioPartition("acme")

    async def _scope(self):
        return RequestScope(user_id=None, tenant="acme", groups=frozenset())


def _app(pool) -> web.Application:
    app = web.Application(middlewares=[_session])
    app["database"] = pool
    manager = BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True,
                         enable_swagger_api=False)
    manager.setup_registry_only(app)
    setup_studio_routes(app)
    app.router.add_view("/tenant/drafts", _AcmeDrafts)
    app.router.add_view("/tenant/drafts/{name}", _AcmeDrafts)
    app.router.add_view("/tenant/drafts/{name}/activate", _AcmeActivate)
    return app


def _bundle(name="bundled", description="d"):
    return {"name": name, "definition": {"bot_class": "BasicBot", "description": description}}


async def _save(client, name="bundled", prefix=BASE, user="u1", **extra):
    resp = await client.post(f"{prefix}/drafts", json={"name": name, "bundle": _bundle(name), **extra},
                             headers={"X-User": user})
    return resp, await resp.json()


async def _activate(client, name="bundled", prefix=BASE, user="u1", **body):
    resp = await client.post(f"{prefix}/drafts/{name}/activate", json=body, headers={"X-User": user})
    return resp, await resp.json()


async def test_bundle_save_and_activate_shapes(aiohttp_client, pool, tmp_path):
    client = await aiohttp_client(_app(pool))
    resp, body = await _save(client)
    assert resp.status == 201
    assert body["name"] == "bundled" and body["file_path"] is None and body["kind"] == "declarative"
    assert body["version"] == 1 and body["status"] == "draft" and "validation_report" in body
    item = await (await client.get(f"{BASE}/drafts/bundled")).json()
    for key in ("draft_id", "name", "status", "validation_report", "kind", "bundle", "tenant", "visibility",
                "allowed_groups", "version", "owner_user_id"):
        assert key in item, key
    assert item["kind"] == "declarative" and item["bundle"]["name"] == "bundled" and item["tenant"] is None
    listing = await (await client.get(f"{BASE}/drafts")).json()
    assert [d["name"] for d in listing["drafts"]] == ["bundled"] and listing["count"] == 1
    resp, body = await _activate(client)
    assert resp.status == 200
    assert body["name"] == "bundled" and body["activated"] is True and body["file_path"] is None
    assert body["agent_id"] and body["version"] >= 1
    agent = await client.app["studio_storage"].services.agents.get(StudioPartition.GLOBAL, "bundled")
    assert str(agent.agent_id) == body["agent_id"]
    again, err = await _activate(client)
    assert again.status == 409 and err["code"] == "version_conflict"
    assert not (tmp_path / "agents").exists()


async def test_tenant_python_draft_refused(aiohttp_client, pool, tmp_path):
    client = await aiohttp_client(_app(pool))
    before = set(sys.modules)
    resp = await client.post("/tenant/drafts", json={"name": "py1", "source": PY_SOURCE})
    body = await resp.json()
    assert resp.status == 422 and body["code"] == "declarative_only"
    assert not (tmp_path / "agents").exists()
    assert set(sys.modules) == before
    resp, body = await _save(client, "ten1", prefix="/tenant")
    assert resp.status == 201
    assert (await client.get("/tenant/drafts/ten1")).status == 200
    assert (await client.get(f"{BASE}/drafts/ten1")).status == 404


async def test_python_drafts_setting_false_refuses_global(aiohttp_client, pool, tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_PYTHON_DRAFTS", "false")
    client = await aiohttp_client(_app(pool))
    resp = await client.post(f"{BASE}/drafts", json={"name": "py2", "source": PY_SOURCE})
    assert resp.status == 422 and (await resp.json())["code"] == "declarative_only"
    assert not (tmp_path / "agents").exists()


async def test_exactly_one_body(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    for payload in ({"name": "x"}, {"name": "x", "source": PY_SOURCE, "bundle": _bundle("x")}):
        resp = await client.post(f"{BASE}/drafts", json=payload)
        assert resp.status == 422 and (await resp.json())["code"] == "invalid_request"


async def test_legacy_python_draft_global(aiohttp_client, pool, tmp_path):
    client = await aiohttp_client(_app(pool))
    resp = await client.post(f"{BASE}/drafts", json={"name": "legacy1", "source": PY_SOURCE})
    body = await resp.json()
    assert resp.status == 201 and body["status"] == "validated"
    assert (tmp_path / "agents" / "_drafts" / "legacy1.py").exists()
    item = await (await client.get(f"{BASE}/drafts/legacy1")).json()
    assert item["kind"] == "python" and item["source"] == PY_SOURCE
    await _save(client)
    listing = await (await client.get(f"{BASE}/drafts")).json()
    kinds = {d["name"]: d["kind"] for d in listing["drafts"]}
    assert kinds == {"bundled": "declarative", "legacy1": "python"}


async def test_stale_draft_update_409(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    await _save(client)
    resp, body = await _save(client, expected_version=1)
    assert resp.status == 201 and body["version"] == 2
    resp, body = await _save(client, expected_version=1)
    assert resp.status == 409 and body["code"] == "version_conflict"
    rec = await client.app["studio_storage"].services.drafts.get(StudioPartition.GLOBAL, "bundled")
    assert rec.version == 2


async def test_update_by_non_owner_refused(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    await _save(client)
    resp, body = await _save(client, user="u2")
    assert resp.status == 409 and body["code"] == "name_taken"   # FEAT-605: a draft the caller cannot manage is name_taken
    resp, body = await _activate(client, user="u2")
    assert resp.status == 403 and body["code"] == "forbidden"


async def test_concurrent_activation_http(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    await _save(client)
    results = await asyncio.gather(_activate(client), _activate(client))
    assert sorted(r.status for r, _ in results) == [200, 409]
    assert {b["code"] for r, b in results if r.status == 409} == {"version_conflict"}
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT count(*) FROM navigator.ai_agents WHERE name = 'bundled'")
    assert count == 1


async def test_activate_replace_target_expected_version(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    await _save(client)
    resp, body = await _activate(client)
    assert resp.status == 200
    version = body["version"]
    resp, body = await _save(client, description="x")  # the draft is already activated: update stays allowed
    assert resp.status == 201
    resp, body = await _activate(client)
    assert resp.status == 409  # activated draft: not activatable again
    await client.app["studio_storage"].services.drafts.delete(StudioPartition.GLOBAL, "bundled")
    resp, body = await _save(client)
    assert resp.status == 201
    resp, body = await _activate(client)
    assert resp.status == 409 and body["code"] == "name_taken"
    resp, body = await _activate(client, replace=True, target_expected_version=version + 5)
    assert resp.status == 409 and body["code"] == "version_conflict"
    resp, body = await _activate(client, replace=True, target_expected_version=version)
    assert resp.status == 200 and body["version"] > version


async def test_stale_activation_expected_version_409(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    await _save(client)
    resp, body = await _activate(client, expected_version=7)
    assert resp.status == 409 and body["code"] == "version_conflict"
    rec = await client.app["studio_storage"].services.drafts.get(StudioPartition.GLOBAL, "bundled")
    assert rec.status == "draft"
    resp, _ = await _activate(client, expected_version=1)
    assert resp.status == 200


# ---- review fixes: access before 409/400, GLOBAL visibility, DELETE /drafts/{name} -------------------------------
class _Resolver:
    """A real ScopeResolver: the caller is the ``X-User`` header, the tenant is always ``acme`` (opted-in host)."""

    async def resolve(self, request):
        return RequestScope(user_id=request.headers.get("X-User", "u1"), tenant="acme", groups=frozenset())


def _opted_app(pool) -> web.Application:
    app = _app(pool)
    app["scope_resolver"] = _Resolver()
    return app


async def test_activate_checks_access_before_409_and_400(aiohttp_client, pool):
    client = await aiohttp_client(_opted_app(pool))
    acme = StudioPartition("acme")
    await _save(client)                                                   # u1's private draft in acme
    await client.app["studio_storage"].services.agents.create(            # a name collision for the activation
        acme, name="bundled", owner="u1", definition=StudioAgentDefinition(description="x"))
    for user, bad_body in (("u2", {"replace": "not-a-bool"}), ("u2", {})):
        resp, body = await _activate(client, user=user, **bad_body)       # invisible: 404 even though 400/409 apply
        assert resp.status == 404 and body["code"] == "not_found", body
    resp, body = await _activate(client, replace="not-a-bool")            # the owner does get the 400 ...
    assert resp.status == 400 and body["code"] == "invalid_request"
    resp, body = await _activate(client)                                  # ... and the 409 collision
    assert resp.status == 409 and body["code"] == "name_taken"


async def test_activate_invisible_draft_404_even_when_not_activatable(aiohttp_client, pool):
    client = await aiohttp_client(_opted_app(pool))
    await _save(client)
    resp, _ = await _activate(client)
    assert resp.status == 200                                             # activated: a second activate is a 409 ...
    resp, body = await _activate(client, user="u2")
    assert resp.status == 404 and body["code"] == "not_found"            # ... which an invisible caller never sees
    resp, body = await _activate(client)
    assert resp.status == 409 and body["code"] == "version_conflict"


async def test_global_draft_refuses_non_private_visibility(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    for extra in ({"visibility": "tenant"}, {"visibility": "groups", "allowed_groups": ["g1"]},
                  {"visibility": "private", "allowed_groups": ["g1"]}):
        resp, body = await _save(client, **extra)
        assert resp.status == 422 and body["code"] == "tenant_required", (extra, body)
    assert await client.app["studio_storage"].services.drafts.get(StudioPartition.GLOBAL, "bundled") is None
    await _save(client)
    resp, body = await _save(client, visibility="tenant")                 # an update of an existing draft too
    assert resp.status == 422 and body["code"] == "tenant_required"
    resp, _ = await _save(client, visibility="private")
    assert resp.status == 201
    resp, _ = await _save(client, "ten2", prefix="/tenant", visibility="tenant")   # a tenant partition may share
    assert resp.status == 201


async def _delete(client, name="bundled", prefix=BASE, user="u1", **params):
    resp = await client.delete(f"{prefix}/drafts/{name}", params=params, headers={"X-User": user})
    return resp, (await resp.json() if resp.content_type == "application/json" else await resp.text())


async def test_delete_declarative_draft(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    svc = client.app["studio_storage"].services.drafts
    await _save(client)
    resp, body = await _delete(client, user="u2")                         # not the owner (GLOBAL lists all): 403
    assert resp.status == 403 and body["code"] == "forbidden"
    assert await svc.get(StudioPartition.GLOBAL, "bundled") is not None
    resp, body = await _delete(client, expected_version="1")              # not an expected_version route (§2.9)
    assert resp.status == 400 and body["code"] == "expected_version_unsupported"
    assert await svc.get(StudioPartition.GLOBAL, "bundled") is not None
    resp, body = await _delete(client)
    assert resp.status == 200 and body == {"name": "bundled", "deleted": True}
    assert await svc.get(StudioPartition.GLOBAL, "bundled") is None
    resp, body = await _delete(client)
    assert resp.status == 404 and body["code"] == "not_found"


async def test_delete_invisible_draft_is_404(aiohttp_client, pool):
    client = await aiohttp_client(_opted_app(pool))
    await _save(client)
    resp, body = await _delete(client, user="u2")
    assert resp.status == 404 and body["code"] == "not_found"
    resp, _ = await _delete(client, user="u2", expected_version="1")      # no 400 leak either
    assert resp.status == 404
    assert await client.app["studio_storage"].services.drafts.get(StudioPartition("acme"), "bundled") is not None
    resp, _ = await _delete(client)
    assert resp.status == 200


async def test_delete_tenant_partition_never_touches_global(aiohttp_client, pool, tmp_path):
    client = await aiohttp_client(_app(pool))
    await _save(client)                                                   # a GLOBAL declarative draft
    await client.post(f"{BASE}/drafts", json={"name": "legacy1", "source": PY_SOURCE})   # and a GLOBAL Python one
    resp, body = await _delete(client, "legacy1", prefix="/tenant")
    assert resp.status == 404 and body["code"] == "not_found"
    assert (tmp_path / "agents" / "_drafts" / "legacy1.py").exists()
    resp, body = await _delete(client, prefix="/tenant")                  # same name, tenant partition: not found
    assert resp.status == 404 and body["code"] == "not_found"
    assert await client.app["studio_storage"].services.drafts.get(StudioPartition.GLOBAL, "bundled") is not None
    await _save(client, "ten1", prefix="/tenant")
    resp, _ = await _delete(client, "ten1", prefix="/tenant")
    assert resp.status == 200
    assert await client.app["studio_storage"].services.drafts.get(StudioPartition("acme"), "ten1") is None


async def test_delete_legacy_python_draft_on_global(aiohttp_client, pool, tmp_path):
    client = await aiohttp_client(_app(pool))
    await client.post(f"{BASE}/drafts", json={"name": "legacy1", "source": PY_SOURCE})
    path = tmp_path / "agents" / "_drafts" / "legacy1.py"
    assert path.exists()
    resp, body = await _delete(client, "legacy1", user="u2")              # legacy owner rule still applies
    assert resp.status == 403
    resp, body = await _delete(client, "legacy1")
    assert resp.status == 200 and body == {"name": "legacy1", "deleted": True} and not path.exists()
    resp, body = await _delete(client, "legacy1")
    assert resp.status == 404 and body["code"] == "not_found"


class _SwapAfterAccess(StudioDraftsHandler):
    """The first access decision is followed by the draft being replaced by another owner at a higher version."""

    swapped = False
    mode = "other_owner"

    async def _check_record_access(self, access, rec, kind, name, *, manage=False):
        denied = await super()._check_record_access(access, rec, kind, name, manage=manage)
        if not type(self).swapped and kind == "draft" and manage:
            type(self).swapped = True
            svc = self._studio_storage().services.drafts
            owner = "u2" if type(self).mode == "other_owner" else "u1"
            assert await svc.delete(StudioPartition.GLOBAL, name)
            bundle = StudioAgentBundle.model_validate(_bundle(name))
            await svc.save_bundle(StudioPartition.GLOBAL, owner=owner, bundle=bundle)
            await svc.save_bundle(StudioPartition.GLOBAL, owner=owner, bundle=bundle)   # version 2
        return denied


async def _swap_client(aiohttp_client, pool, mode):
    _SwapAfterAccess.swapped, _SwapAfterAccess.mode = False, mode
    app = _app(pool)
    app.router.add_view("/swap/drafts/{name}", _SwapAfterAccess)
    return await aiohttp_client(app)


async def test_delete_stale_authorization_reauthorizes_and_refuses(aiohttp_client, pool):
    client = await _swap_client(aiohttp_client, pool, "other_owner")
    await _save(client)
    resp, body = await _delete(client, prefix="/swap")                    # u1 authorized v1; the row is now u2's v2
    assert resp.status == 403 and body["code"] == "forbidden"
    rec = await client.app["studio_storage"].services.drafts.get(StudioPartition.GLOBAL, "bundled")
    assert rec is not None and rec.owner == "u2" and rec.version == 2


async def test_delete_stale_authorization_retries_when_still_allowed(aiohttp_client, pool):
    client = await _swap_client(aiohttp_client, pool, "same_owner")
    await _save(client)
    resp, body = await _delete(client, prefix="/swap")                    # re-read, re-authorized (still u1's), retried
    assert resp.status == 200 and body == {"name": "bundled", "deleted": True}
    assert await client.app["studio_storage"].services.drafts.get(StudioPartition.GLOBAL, "bundled") is None
