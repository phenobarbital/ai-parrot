"""``BotManager._register_a2ui_deeplink_routes`` tests (FEAT-469 TASK-2574)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from aiohttp import web
from parrot.manager.manager import BotManager

pytestmark = pytest.mark.asyncio


def _manager_with_app(app: web.Application) -> BotManager:
    manager = BotManager(enable_registry_bots=False, enable_crews=False)
    manager.app = app
    return manager


def _routed_paths(app: web.Application) -> set[str]:
    return {route.resource.canonical for route in app.router.routes() if route.resource is not None}


async def test_deeplink_routes_mounted():
    app = web.Application()
    app["redis"] = MagicMock()
    manager = _manager_with_app(app)

    manager._register_a2ui_deeplink_routes()

    assert "/api/v1/a2ui/resume/web" in _routed_paths(app)


async def test_duplicate_registration_warns_not_raises(caplog):
    app = web.Application()
    app["redis"] = MagicMock()
    manager = _manager_with_app(app)
    manager._register_a2ui_deeplink_routes()

    with caplog.at_level("WARNING"):
        manager._register_a2ui_deeplink_routes()  # second call on the SAME app — must not raise

    assert any("already registered" in rec.message for rec in caplog.records)
    # Still exactly one GET/HEAD/POST route set for the path, not duplicated
    # (aiohttp auto-adds HEAD alongside GET).
    matching = [r for r in app.router.routes() if r.resource is not None and r.resource.canonical == "/api/v1/a2ui/resume/web"]
    assert len(matching) == 3  # GET + HEAD + POST


async def test_missing_redis_skips_gracefully(caplog):
    app = web.Application()  # no app["redis"]
    manager = _manager_with_app(app)

    with caplog.at_level("WARNING"):
        manager._register_a2ui_deeplink_routes()

    assert "/api/v1/a2ui/resume/web" not in _routed_paths(app)
    assert any("not mounted" in rec.message for rec in caplog.records)
