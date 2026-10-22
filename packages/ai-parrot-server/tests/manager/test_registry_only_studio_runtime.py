"""FEAT-605 W2.2 — registry-only mount installs FEAT-621's Studio runtime once."""
from __future__ import annotations

import pytest
from aiohttp import web

from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio.storage.backend import STUDIO_STORAGE_APP_KEY, StudioStorage
from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories
from parrot.manager import studio_runtime as runtime_module
from parrot.manager.manager import BotManager
from parrot.manager.studio_runtime import (
    StudioAgentRuntime,
    install_studio_runtime,
    shutdown_studio_runtime,
)


def _manager() -> BotManager:
    return BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True,
                      enable_swagger_api=False)


def _app(order: str, prefixes=("/api/v1/astudio",)):
    """An app with a ``database``-backend storage over the in-memory fake, mounted in the given order."""
    app, mgr = web.Application(), _manager()
    app[STUDIO_STORAGE_APP_KEY] = StudioStorage("database", None, InMemoryStudioRepositories(), app)
    if order == "documented":
        mgr.setup_registry_only(app)
        for prefix in prefixes:
            setup_studio_routes(app, prefix=prefix)
    else:
        for prefix in prefixes:
            setup_studio_routes(app, prefix=prefix)
        mgr.setup_registry_only(app)
    return app, mgr


@pytest.fixture(autouse=True)
def _runtime_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(tmp_path / "rt"))
    monkeypatch.setenv("STUDIO_SWEEP_INTERVAL_SECONDS", "3600")


@pytest.mark.parametrize("order", ["documented", "reverse"])
async def test_registry_only_installs_studio_runtime(order):
    app, mgr = _app(order)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        assert isinstance(mgr.studio, StudioAgentRuntime)
        assert mgr.studio.app is app
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("order", ["documented", "reverse"])
async def test_registry_only_runtime_hooks_once(order):
    app, mgr = _app(order, prefixes=("/api/v1/astudio", "/t/{tenant}/astudio"))
    mgr.setup_registry_only(app)
    assert list(app.on_startup).count(install_studio_runtime) == 1
    assert list(app.on_cleanup).count(shutdown_studio_runtime) == 1
    resolve = [h for h in app.on_startup if getattr(h, "__name__", "") == "resolve_studio_storage"]
    assert len(resolve) == 1


@pytest.mark.parametrize("order", ["documented", "reverse"])
async def test_registry_only_shutdown_runs_studio_shutdown(order, monkeypatch):
    app, mgr = _app(order)
    calls = []
    real = runtime_module.StudioAgentRuntime.shutdown

    async def spy(self):
        calls.append(self)
        await real(self)

    monkeypatch.setattr(runtime_module.StudioAgentRuntime, "shutdown", spy)
    seen = []
    original = mgr._cleanup_all_bots

    async def cleanup_spy(a):
        seen.append(getattr(mgr, "studio", None))
        await original(a)

    app.on_cleanup[app.on_cleanup.index(original)] = cleanup_spy
    runner = web.AppRunner(app)
    await runner.setup()
    runtime = mgr.studio
    await runner.cleanup()
    assert calls == [runtime]
    assert runtime._sweep_task is None
