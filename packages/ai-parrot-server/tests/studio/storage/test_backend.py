"""FEAT-621 M4 — backend matrix (§2.2) and partition hook."""

import asyncio
import os

import pytest
from aiohttp import web

from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio._base import StudioBaseView
from parrot.handlers.studio.storage import backend as be
from parrot.handlers.studio.storage import migrate
from parrot.handlers.studio.storage.models import StudioPartition, StudioStorageUnavailable

from .conftest import real_request

REQ = migrate.STUDIO_SCHEMA_REQUIRED


def _manifest() -> dict[int, str]:
    return {m.version: m.checksum for m in migrate.list_migrations()}


def _state(*, present=True, upto=REQ, drift=None, server=170000) -> migrate.LedgerState:
    manifest = _manifest()
    applied = {v: manifest[v] for v in range(1, upto + 1)} if present else {}
    if drift:
        applied[drift] = "0" * 64
    return migrate.LedgerState(present, applied, server)


class _FakeConn:
    pass


class _FakePool:
    def __init__(self):
        self.acquired = 0

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                pool.acquired += 1
                await asyncio.sleep(0)
                return _FakeConn()

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


CASES = [
    # setting, pool?, state, expected backend
    ("auto", False, None, "filesystem"),
    ("database", False, None, "unavailable"),
    ("filesystem", True, None, "filesystem"),
    ("auto", True, _state(present=False), "filesystem"),
    ("database", True, _state(present=False), "unavailable"),
    ("auto", True, _state(), "database"),
    ("database", True, _state(), "database"),
    ("auto", True, _state(upto=REQ - 1), "unavailable"),
    ("database", True, _state(upto=REQ - 1), "unavailable"),
    ("auto", True, _state(drift=2), "unavailable"),
    ("auto", True, _state(server=130000), "unavailable"),
    ("auto", True, _state(present=False, server=130000), "unavailable"),
    ("database", True, _state(present=False, server=130000), "unavailable"),
    ("auto", True, RuntimeError("boom"), "unavailable"),
]


@pytest.mark.parametrize("setting,has_pool,state,expected", CASES)
def test_backend_resolution_matrix(setting, has_pool, state, expected):
    backend, reason = be._resolve(setting, object() if has_pool else None, state)
    assert backend == expected
    assert (reason is None) == (expected == "database")


@pytest.mark.parametrize("setting,has_pool,state,expected", CASES)
async def test_ensure_resolves_via_probe(monkeypatch, setting, has_pool, state, expected):
    async def _read(conn):
        if isinstance(state, Exception):
            raise state
        return state

    monkeypatch.setattr(be.migrate, "read_ledger", _read)
    monkeypatch.setattr(be.config, "get", lambda key, fallback=None: setting)
    app = web.Application()
    if has_pool:
        app["database"] = _FakePool()
    storage = await be.ensure_studio_storage(app)
    assert storage.backend == expected
    assert (storage.repos is not None) == (expected == "database")
    assert app[be.STUDIO_STORAGE_APP_KEY] is storage


async def test_ensure_is_memoised_and_locked(monkeypatch):
    calls = []

    async def _read(conn):
        calls.append(1)
        await asyncio.sleep(0.01)
        return _state()

    monkeypatch.setattr(be.migrate, "read_ledger", _read)
    monkeypatch.setattr(be.config, "get", lambda key, fallback=None: "auto")
    app = web.Application()
    app["database"] = _FakePool()
    first, second = await asyncio.gather(be.ensure_studio_storage(app), be.ensure_studio_storage(app))
    assert first is second and len(calls) == 1
    assert await be.ensure_studio_storage(app) is first and len(calls) == 1


def test_require_for_tenant_on_filesystem_raises():
    fs = be.StudioStorage("filesystem", "x")
    fs.require_for(StudioPartition.GLOBAL)
    with pytest.raises(StudioStorageUnavailable):
        fs.require_for(StudioPartition("acme"))
    with pytest.raises(StudioStorageUnavailable):
        be.StudioStorage("unavailable", "x").require_for(StudioPartition.GLOBAL)
    be.StudioStorage("database").require_for(StudioPartition("acme"))


def test_hook_registered_once(monkeypatch):
    app = web.Application()
    setup_studio_routes(app)
    monkeypatch.setattr(app.router, "add_view", lambda *a, **k: None)  # re-registering routes is out of scope
    monkeypatch.setattr(app.router, "add_route", lambda *a, **k: None)
    setup_studio_routes(app)
    assert app.on_startup.count(be.resolve_studio_storage) == 1


async def test_studio_partition_default_global():
    app = web.Application()
    req = real_request(app, "GET", "/api/v1/astudio/agents")
    view = StudioBaseView(req)
    assert await view._studio_partition() is StudioPartition.GLOBAL
    app[be.STUDIO_STORAGE_APP_KEY] = storage = be.StudioStorage("filesystem")
    assert view._studio_storage() is storage


async def test_real_postgres_resolves_database(studio_pool):
    if not os.environ.get("TEST_STUDIO_PG_DSN"):
        pytest.skip("TEST_STUDIO_PG_DSN not set")
    app = web.Application()
    app["database"] = studio_pool
    storage = await be.ensure_studio_storage(app)
    assert storage.backend == "database" and storage.repos is not None


async def test_studio_storage_missing_raises_unavailable():
    req = real_request(web.Application(), "GET", "/api/v1/astudio/agents")
    with pytest.raises(StudioStorageUnavailable):
        StudioBaseView(req)._studio_storage()
