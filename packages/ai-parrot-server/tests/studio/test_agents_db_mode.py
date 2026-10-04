"""FEAT-621 W3 agents in database mode (AC4, AC8, AC16, AC18).

Real aiohttp app (``aiohttp_client``), the real Studio routes, a session middleware that installs a real
``SessionData`` and a real Postgres pool. ``AbstractBot.configure`` is replaced so no LLM is ever started.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from asyncdb import AsyncPool
from navigator_session.data import SessionData

from parrot.bots.abstract import AbstractBot
from parrot.bots.basic import BasicBot
from parrot.handlers.studio import agents as agents_module
from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio.agents import StudioAgentsHandler
from parrot.handlers.studio.storage.migrate import apply_studio_migrations
from parrot.handlers.studio.storage.models import StudioPartition, StudioStaleAuthorization
from parrot.manager.manager import BotManager
from parrot.registry import registry as registry_module

BASE = "/api/v1/astudio"
TABLES = ("ai_agent_assets", "ai_agent_tooling", "ai_agent_drafts", "ai_agents", "ai_skills_catalog")


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
    yield pg
    async with pg.acquire() as conn:
        for table in TABLES:
            await conn.execute(f"TRUNCATE navigator.{table} CASCADE")
    await pg.close()


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    """No LLM start-up, runtime directory and AGENTS_DIR bindings inside ``tmp_path``."""
    monkeypatch.setattr(AbstractBot, "configure", AsyncMock())
    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("STUDIO_SWEEP_INTERVAL_SECONDS", "3600")
    monkeypatch.setattr(agents_module, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path / "agents")


@web.middleware
async def _session(request, handler):
    """The real session object; the caller is picked by the ``X-User`` header."""
    user = request.headers.get("X-User", "u1")
    request["NAV_SESSION"] = SessionData(data={"session": {"user_id": user, "groups": [], "superuser": False}})
    request["authenticated"] = True
    return await handler(request)


def _app(pool, *, view=None) -> web.Application:
    app = web.Application(middlewares=[_session])
    app["database"] = pool
    manager = BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True,
                         enable_swagger_api=False)
    manager.setup_registry_only(app)
    setup_studio_routes(app)
    if view is not None:
        app.router.add_view("/tenant/agents", view)
        app.router.add_view("/tenant/agents/{name}", view)
    return app


async def _create(client, name="alpha", user="u1", **extra):
    resp = await client.post(f"{BASE}/agents", json={"name": name, "bot_class": "BasicBot", **extra},
                             headers={"X-User": user})
    return resp, await resp.json()


async def test_services_container_builds(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    storage = client.app["studio_storage"]
    assert storage.backend == "database"
    services = storage.services
    for name in ("agents", "assets", "tooling", "drafts", "skills"):
        assert getattr(services, name) is not None


async def test_create_without_bundle_http(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    resp, body = await _create(client, description="d")
    assert resp.status == 201
    assert body["source"] == "studio" and body["persisted"] is True and body["file_path"] is None
    assert body["tenant"] is None and body["version"] == 1 and body["agent_id"]
    assert "warnings" not in body
    item = await (await client.get(f"{BASE}/agents/alpha")).json()
    assert item["source"] == "studio" and item["origin"] == "studio" and item["owner"] == "u1"
    assert item["agent_id"] == body["agent_id"] and item["visibility"] == "private" and item["allowed_groups"] == []
    listing = await (await client.get(f"{BASE}/agents")).json()
    assert [a["name"] for a in listing["agents"]] == ["alpha"] and listing["count"] == 1
    resp, body = await _create(client, name="beta", persist=False)
    assert resp.status == 201 and body["persisted"] is True
    assert body["warnings"] == ["persist ignored: database storage always persists"]


async def test_create_refusals(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    assert (await _create(client))[0].status == 201
    resp, body = await _create(client)
    assert resp.status == 409 and body["code"] == "name_taken"
    client.app["bot_manager"].registry.register("legacy-one", BasicBot)
    resp, body = await _create(client, name="legacy-one")
    assert resp.status == 409 and body["code"] == "name_taken"
    resp, body = await _create(client, name="gamma", expected_version=3)
    assert resp.status == 400 and body["code"] == "expected_version_unsupported"
    resp = await client.post(f"{BASE}/agents", json={"name": "delta", "bot_class": "NoSuchClass"})
    assert resp.status == 400 and (await resp.json())["code"] == "invalid_bot_class"
    resp, body = await _create(client, name="eps", config={"llm": "openai:gpt-4o"})
    assert resp.status == 422 and body["code"] == "unsupported_config_key"
    resp, body = await _create(client, name="zeta", config={"created_by": "someone"})
    assert resp.status == 400 and body["code"] == "reserved_config_key"


async def test_patch_agent_general_fields(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    await _create(client, description="v1")
    url = f"{BASE}/agents/alpha"
    resp = await client.patch(url, json={"description": "v2", "model_params": {"temperature": 0.5}})
    body = await resp.json()
    assert resp.status == 200 and body["version"] == 2 and body["source"] == "studio"
    resp = await client.patch(url, json={"model_params": {"top_k": 3}, "category": "ops"})
    assert resp.status == 200 and (await resp.json())["version"] == 3
    rec = await client.app["studio_storage"].services.agents.get(StudioPartition.GLOBAL, "alpha")
    assert rec.definition.description == "v2" and rec.definition.category == "ops"
    assert rec.definition.model_params.temperature == 0.5 and rec.definition.model_params.top_k == 3
    resp = await client.patch(url, json={"name": "other"})
    assert resp.status == 422 and (await resp.json())["code"] == "name_immutable"
    assert (await client.patch(url, json={"bot_class": "Agent"})).status == 422
    resp = await client.patch(url, json={"description": "stale", "expected_version": 1})
    assert resp.status == 409 and (await resp.json())["code"] == "version_conflict"
    rec = await client.app["studio_storage"].services.agents.get(StudioPartition.GLOBAL, "alpha")
    assert rec.version == 3 and rec.definition.description == "v2"
    resp = await client.patch(url, json={"description": "ok", "expected_version": 3})
    assert resp.status == 200 and (await resp.json())["version"] == 4
    assert (await client.patch(f"{BASE}/agents/missing", json={"description": "x"})).status == 404
    assert (await client.patch(url, headers={"X-User": "u2"}, json={"description": "x"})).status == 403


async def test_patch_legacy_agent_is_not_studio_agent(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    client.app["bot_manager"].registry.register("legacy-one", BasicBot)
    resp = await client.patch(f"{BASE}/agents/legacy-one", json={"description": "x"})
    assert resp.status == 409 and (await resp.json())["code"] == "not_studio_agent"


async def test_patch_on_filesystem_backend_is_503(aiohttp_client, pool, monkeypatch):
    monkeypatch.setenv("PARROT_STUDIO_STORAGE", "filesystem")
    client = await aiohttp_client(_app(pool))
    assert client.app["studio_storage"].backend == "filesystem"
    resp = await client.patch(f"{BASE}/agents/alpha", json={"description": "x"})
    assert resp.status == 503 and (await resp.json())["code"] == "studio_storage_unavailable"


async def test_delete_guarded(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    await _create(client)
    url = f"{BASE}/agents/alpha"
    assert (await client.delete(url, headers={"X-User": "u2"})).status == 403
    resp = await client.delete(url, params={"expected_version": "9"})
    assert resp.status == 409 and (await resp.json())["code"] == "version_conflict"
    assert (await client.get(url)).status == 200
    assert (await client.delete(url, params={"expected_version": "x"})).status == 400
    resp = await client.delete(url, params={"expected_version": "1"})
    assert resp.status == 200 and await resp.json() == {"name": "alpha", "deleted": True}
    assert (await client.get(url)).status == 404
    assert (await client.delete(url)).status == 404


class _StaleOnce:
    """Wraps a real service method; raises ``StudioStaleAuthorization`` for the first ``times`` calls."""

    def __init__(self, real, times):
        self.real, self.times, self.calls = real, times, 0

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.times:
            raise StudioStaleAuthorization("moved")
        return await self.real(*args, **kwargs)


async def test_stale_authorization_retries_once(aiohttp_client, pool, monkeypatch):
    client = await aiohttp_client(_app(pool))
    await _create(client)
    svc = client.app["studio_storage"].services.agents
    once = _StaleOnce(svc.delete, 1)
    monkeypatch.setattr(svc, "delete", once)
    assert (await client.delete(f"{BASE}/agents/alpha")).status == 200 and once.calls == 2
    await _create(client)
    twice = _StaleOnce(svc.delete, 2)
    monkeypatch.setattr(svc, "delete", twice)
    resp = await client.delete(f"{BASE}/agents/alpha")
    assert resp.status == 409 and (await resp.json())["code"] == "version_conflict" and twice.calls == 2
    assert (await client.get(f"{BASE}/agents/alpha")).status == 200


async def test_reload_studio_agent(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    await _create(client)
    resp = await client.post(f"{BASE}/agents/alpha/reload")
    body = await resp.json()
    assert resp.status == 200 and body["name"] == "alpha" and body["reloaded"] is True
    resp = await client.post(f"{BASE}/agents/alpha/reload", params={"expected_version": "1"})
    assert resp.status == 400 and (await resp.json())["code"] == "expected_version_unsupported"
    resp = await client.post(f"{BASE}/agents/nobody/reload")
    assert resp.status == 404 and (await resp.json())["code"] == "not_found"


class _AcmeAgents(StudioAgentsHandler):
    """A tenant host stand-in: the partition is the ``acme`` tenant."""

    async def _studio_partition(self):
        return StudioPartition("acme")


async def test_tenant_partition_lists_studio_rows_only(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool, view=_AcmeAgents))
    client.app["bot_manager"].registry.register("legacy-one", BasicBot)
    await _create(client, name="global-one")
    resp = await client.post("/tenant/agents", json={"name": "tenant-one", "bot_class": "BasicBot"})
    body = await resp.json()
    assert resp.status == 201 and body["tenant"] == "acme"
    listing = await (await client.get("/tenant/agents")).json()
    assert [a["name"] for a in listing["agents"]] == ["tenant-one"]
    names = [a["name"] for a in (await (await client.get(f"{BASE}/agents")).json())["agents"]]
    assert "tenant-one" not in names and {"global-one", "legacy-one"} <= set(names)
    assert (await client.get("/tenant/agents/global-one")).status == 404
    assert (await client.get("/tenant/agents/legacy-one")).status == 404


async def test_tenant_partition_on_filesystem_is_503(aiohttp_client, pool, monkeypatch):
    monkeypatch.setenv("PARROT_STUDIO_STORAGE", "filesystem")
    client = await aiohttp_client(_app(pool, view=_AcmeAgents))
    assert client.app["studio_storage"].backend == "filesystem"
    for call in (client.get("/tenant/agents"), client.get("/tenant/agents/x"),
                 client.post("/tenant/agents", json={"name": "x"}),
                 client.delete("/tenant/agents/x"), client.patch("/tenant/agents/x", json={})):
        resp = await call
        assert resp.status == 503 and (await resp.json())["code"] == "studio_storage_unavailable"


async def test_nothing_written_under_agents_dir(aiohttp_client, pool, tmp_path):
    client = await aiohttp_client(_app(pool))
    await _create(client, persist=True, category="ops")
    await client.patch(f"{BASE}/agents/alpha", json={"description": "x"})
    await client.post(f"{BASE}/agents/alpha/reload")
    await client.delete(f"{BASE}/agents/alpha")
    assert not (tmp_path / "agents").exists() or not list((tmp_path / "agents").rglob("*"))


class _DenyUpdates:
    """A PDP evaluator that denies every ``*:update`` / ``*:create`` action and allows the rest."""

    def check_access(self, ctx, resource_type, resource, action):
        from types import SimpleNamespace

        return SimpleNamespace(allowed=not action.endswith((":update", ":create")))


async def test_pbac_gate_applies_in_database_mode(aiohttp_client, pool):
    from types import SimpleNamespace

    app = _app(pool)
    app["abac"] = SimpleNamespace(_evaluator=_DenyUpdates())
    client = await aiohttp_client(app)
    resp, body = await _create(client)
    assert resp.status == 403 and body["code"] == "pbac_denied"
    assert (await client.patch(f"{BASE}/agents/alpha", json={"description": "x"})).status == 403
    assert (await client.get(f"{BASE}/agents")).status == 200


async def test_studio_items_keep_the_registry_keys(aiohttp_client, pool):
    """§2.9 is additive-only: a Studio item keeps the six registry keys of the filesystem-mode item."""
    client = await aiohttp_client(_app(pool))
    await _create(client)
    keys = {"at_startup", "class_name", "file_path", "module", "priority", "tags"}
    one = await (await client.get(f"{BASE}/agents/alpha")).json()
    listed = (await (await client.get(f"{BASE}/agents")).json())["agents"][0]
    for item in (one, listed):
        assert keys <= set(item)
        assert item["class_name"] == "BasicBot" and item["tags"] == [] and item["at_startup"] is False
