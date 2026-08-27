"""Unit tests for the Admin status endpoint (FEAT-468, TASK-2524).

Covers ``GET /api/v1/admin/status``: auth enforcement, response shape,
and graceful degradation when a dependency probe fails (never a 500).

Follows the same authenticated-app testing pattern established by
``tests/integration/test_saas_auth_hardening.py``, but stays
infra-free: this sandbox has no live Postgres/Redis (the full
``navigator_auth.AuthHandler().setup(app)`` stack that suite's
``anon_app`` fixture uses fails to connect here — confirmed by running
that suite unmodified). The anonymous-rejection case instead drives the
exact same ``is_authenticated()`` production code path
(``navigator_auth/decorators.py::get_auth`` -> ``auth.backends`` loop)
with an ``app["auth"]`` stand-in that has zero backends, so ``userdata``
stays ``None`` and the real 401 branch fires — no backend is faked,
only the (empty) container that would normally hold configured OAuth/
Basic backends. The authenticated case reuses the
``request["authenticated"]`` short-circuit + monkeypatched
``get_session`` substitute verbatim.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot.server.ui import setup_admin_ui
from parrot.server.ui.status import AdminStatusHandler


class _FakeSession(dict):
    """Minimal session stand-in matching the ``user_session()`` contract."""

    def decode(self, key):
        return self.get(f"__decoded_{key}__")


class _FakeBot:
    """Bot stand-in shaped like ``AbstractBot``: ``_vector_store`` is the
    raw config dict (never a store instance — see ``bots/abstract.py:573``),
    ``store`` is the actual configured ``AbstractStore`` (or ``None``)."""

    def __init__(self, *, vector_store_config=None, store=None):
        self._vector_store = vector_store_config
        self.store = store


def _stub_bot_manager(*, bots=None):
    bot_manager = MagicMock()
    bot_manager.get_bots = MagicMock(
        return_value=bots if bots is not None else {"a": _FakeBot(), "b": _FakeBot()}
    )
    bot_manager.registry = MagicMock()
    bot_manager.registry.list_agents = MagicMock(return_value=[object(), object(), object()])
    bot_manager.list_crews = MagicMock(return_value={"crew-a": (object(), object())})
    return bot_manager


@pytest.fixture
def anon_app():
    """``app["auth"]`` present with zero backends -> the real
    ``is_authenticated()`` "no userdata" 401 branch fires, without needing
    a live auth backend."""
    app = web.Application()
    app["auth"] = SimpleNamespace(backends={})
    app.router.add_view("/api/v1/admin/status", AdminStatusHandler)
    return app


def _build_authenticated_app(monkeypatch, bot_manager):
    """Admin status route mounted with every request treated as
    authenticated and a fully-controlled fake session."""

    @web.middleware
    async def _mark_authenticated(request: web.Request, handler):
        request["authenticated"] = True
        return await handler(request)

    async def _fake_get_session(request, new=False):
        return request.app["_test_session"]

    monkeypatch.setattr(
        "navigator_auth.decorators.get_session", _fake_get_session
    )

    app = web.Application(middlewares=[_mark_authenticated])
    app["_test_session"] = _FakeSession()
    app["bot_manager"] = bot_manager
    setup_admin_ui(app)
    return app


@pytest.fixture
def authenticated_app(monkeypatch):
    return _build_authenticated_app(monkeypatch, _stub_bot_manager())


class TestRequiresAuth:
    async def test_unauthenticated_get_returns_401(self, aiohttp_client, anon_app):
        client = await aiohttp_client(anon_app)
        resp = await client.get("/api/v1/admin/status")
        assert resp.status == 401


class TestShape:
    async def test_authenticated_get_matches_admin_status_shape(
        self, aiohttp_client, authenticated_app
    ):
        client = await aiohttp_client(authenticated_app)
        resp = await client.get("/api/v1/admin/status")
        assert resp.status == 200
        body = await resp.json()

        assert body["version"]
        assert body["uptime_seconds"] >= 0
        assert body["agents"] == {"database": 0, "registry": 3, "loaded": 2}
        assert body["crews"] == 1
        assert set(body["dependencies"].keys()) == {
            "postgres", "redis", "vector_store",
        }
        # No app['database']/app['redis'] wired -> both unconfigured; no
        # bot has a configured `.store` -> vector_store also unconfigured.
        for dep in body["dependencies"].values():
            assert dep["status"] == "unconfigured"


class TestDegradedDependency:
    async def test_dead_redis_degrades_its_entry_not_the_endpoint(
        self, aiohttp_client, authenticated_app
    ):
        fake_redis = MagicMock()
        fake_redis.ping = AsyncMock(side_effect=TimeoutError("redis down"))
        authenticated_app["redis"] = fake_redis

        client = await aiohttp_client(authenticated_app)
        resp = await client.get("/api/v1/admin/status")

        assert resp.status == 200
        body = await resp.json()
        assert body["dependencies"]["redis"]["status"] == "unreachable"


class TestVectorStoreProbe:
    """Regression coverage for the code-review CRITICAL finding: the probe
    must read ``bot.store`` (the real ``AbstractStore`` instance), never
    ``bot._vector_store`` (the raw config dict — always truthy once set,
    which previously made every configured-but-healthy store report
    "unreachable", and a `{}`-default bot report "unreachable" instead of
    "unconfigured")."""

    async def test_connected_store_reports_ok(self, monkeypatch, aiohttp_client):
        store = MagicMock()
        store.is_connected = MagicMock(return_value=True)
        bot_manager = _stub_bot_manager(
            bots={"a": _FakeBot(vector_store_config={"name": "pgvector"}, store=store)}
        )
        app = _build_authenticated_app(monkeypatch, bot_manager)

        client = await aiohttp_client(app)
        resp = await client.get("/api/v1/admin/status")
        body = await resp.json()
        assert body["dependencies"]["vector_store"]["status"] == "ok"

    async def test_disconnected_store_reports_unreachable(self, monkeypatch, aiohttp_client):
        store = MagicMock()
        store.is_connected = MagicMock(return_value=False)
        bot_manager = _stub_bot_manager(
            bots={"a": _FakeBot(vector_store_config={"name": "pgvector"}, store=store)}
        )
        app = _build_authenticated_app(monkeypatch, bot_manager)

        client = await aiohttp_client(app)
        resp = await client.get("/api/v1/admin/status")
        body = await resp.json()
        assert body["dependencies"]["vector_store"]["status"] == "unreachable"

    async def test_config_dict_without_store_instance_is_unconfigured(
        self, monkeypatch, aiohttp_client
    ):
        """A bot with only a raw ``vector_store_config`` dict and no
        connected ``.store`` yet must report "unconfigured", not
        "unreachable" (the dict itself must never be mistaken for a store)."""
        bot_manager = _stub_bot_manager(
            bots={"a": _FakeBot(vector_store_config={"name": "pgvector"}, store=None)}
        )
        app = _build_authenticated_app(monkeypatch, bot_manager)

        client = await aiohttp_client(app)
        resp = await client.get("/api/v1/admin/status")
        body = await resp.json()
        assert body["dependencies"]["vector_store"]["status"] == "unconfigured"


class TestRegisteredWithoutDist:
    async def test_status_route_registers_even_without_dist(self, tmp_path, monkeypatch):
        from parrot.server.ui import serving

        monkeypatch.setattr(serving, "_dist_dir", lambda: tmp_path / "no-dist-here")
        monkeypatch.setattr(serving, "_warned_missing_dist", False)

        app = web.Application()
        result = setup_admin_ui(app)

        assert result is False
        paths = {r.resource.canonical for r in app.router.routes()}
        assert "/api/v1/admin/status" in paths
