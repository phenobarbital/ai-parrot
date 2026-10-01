"""FEAT-605 M4 — BotManager.setup(studio_routes=) and setup_registry_only (manager-level lifecycle)."""
from __future__ import annotations

import pytest
from aiohttp import web
from parrot.manager.manager import BotManager


def _manager() -> BotManager:
    return BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True,
                      enable_swagger_api=False)


def _astudio_routes(app: web.Application) -> list[str]:
    return [r.resource.canonical for r in app.router.routes()
            if r.resource is not None and "astudio" in r.resource.canonical]


def test_studio_routes_flag():
    app = web.Application()
    _manager().setup(app, studio_routes=False)
    assert _astudio_routes(app) == []


def test_studio_routes_default_mounts():
    app = web.Application()
    _manager().setup(app)
    assert _astudio_routes(app)


def test_registry_only_no_routes():
    app, mgr = web.Application(), _manager()
    mgr.setup_registry_only(app)
    assert len(app.router.routes()) == 0
    assert app["bot_manager"] is mgr


def test_registry_only_hooks_once():
    app, mgr = web.Application(), _manager()
    base = (len(app.on_startup), len(app.on_shutdown), len(app.on_cleanup))
    mgr.setup_registry_only(app)
    mgr.setup_registry_only(app)
    got = (len(app.on_startup), len(app.on_shutdown), len(app.on_cleanup))
    assert got == (base[0] + 1, base[1] + 1, base[2] + 1)


async def test_registry_only_manager_lifecycle():
    app, mgr = web.Application(), _manager()
    mgr.setup_registry_only(app)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        task = mgr._cleanup_task
        assert task is not None and not task.done()
    finally:
        await runner.cleanup()
    assert mgr._cleanup_task is None
    assert task.cancelled() or task.done()


def test_registry_only_refuses_imports_in_tenant_host():
    class _R:
        async def resolve(self, request):  # pragma: no cover
            raise AssertionError

    for kw in ({"import_modules": True}, {"load_definitions": True}):
        app = web.Application()
        app["scope_resolver"] = _R()
        with pytest.raises(RuntimeError):
            _manager().setup_registry_only(app, **kw)
    # non-tenant host: allowed
    _manager().setup_registry_only(web.Application(), import_modules=True)
