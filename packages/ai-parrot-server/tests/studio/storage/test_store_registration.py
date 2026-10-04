"""FEAT-621 phase 2 — Postgres store registration at startup: fail closed, per-app lifecycle (review fixes 2, 9)."""
from __future__ import annotations

import pytest
from aiohttp import web
from navigator_session.vault import KeyRing

import parrot.auth.broker as broker_module
import parrot.security.vault_utils as vault_utils
from parrot.handlers import toolkit_persistence
from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio.storage import backend as backend_module
from parrot.handlers.studio.storage import byok_store as byok_module
from parrot.manager.studio_runtime import add_studio_runtime_hooks

SWITCHES = ("VAULT_STORE", "TOOLKIT_OVERRIDES_STORE", "BYOK_STORE")
KEYRING = KeyRing({1: b"1" * 32}, 1)


def _registered() -> dict[str, bool]:
    return {
        "VAULT_STORE": vault_utils._PG_VAULT_STORE is not None,
        "TOOLKIT_OVERRIDES_STORE": toolkit_persistence._PG_OVERRIDES is not None,
        "BYOK_STORE": broker_module._PG_STORE is not None,
    }


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in SWITCHES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(byok_module, "get_vault_keyring", lambda: KEYRING)
    yield
    vault_utils.set_vault_credential_store(None)
    toolkit_persistence.set_toolkit_override_store(None)
    byok_module.register_byok_store(None)


@pytest.mark.parametrize("setting", ["filesystem", "database"])    # database + no pool == unavailable
@pytest.mark.parametrize("switch", SWITCHES)
async def test_postgres_switch_without_database_backend_raises(monkeypatch, switch, setting):
    monkeypatch.setenv(switch, "postgres")
    monkeypatch.setenv("PARROT_STUDIO_STORAGE", setting)
    app = web.Application()
    for _ in range(2):                                              # lazy re-invocation fails the same way
        with pytest.raises(backend_module.StudioStorageMisconfigured, match=switch):
            await backend_module.ensure_studio_storage(app)
    assert backend_module.STUDIO_STORAGE_APP_KEY not in app and not any(_registered().values())


@pytest.mark.parametrize("switch", SWITCHES)
async def test_postgres_switch_with_database_backend_registers(monkeypatch, studio_pool, switch):
    monkeypatch.setenv(switch, "postgres")
    monkeypatch.setenv("PARROT_STUDIO_STORAGE", "database")
    app = web.Application()
    app["database"] = studio_pool
    assert (await backend_module.ensure_studio_storage(app)).backend == "database"
    assert _registered() == {name: name == switch for name in SWITCHES}


async def test_cleanup_clears_registrations_and_second_app_is_unaffected(monkeypatch, studio_pool):
    """Two apps sequentially in one process: app1's cleanup clears its stores; app2 (switches off) sees none."""
    for name in SWITCHES:
        monkeypatch.setenv(name, "postgres")
    monkeypatch.setenv("PARROT_STUDIO_STORAGE", "database")
    app1 = web.Application()
    app1["database"] = studio_pool
    await backend_module.ensure_studio_storage(app1)
    assert all(_registered().values())
    await backend_module.release_studio_stores(app1)
    assert not any(_registered().values())
    await backend_module.release_studio_stores(app1)                # idempotent

    for name in SWITCHES:
        monkeypatch.setenv(name, "documentdb")
    app2 = web.Application()
    app2["database"] = studio_pool
    assert (await backend_module.ensure_studio_storage(app2)).backend == "database"
    assert not any(_registered().values())


async def test_cleanup_of_an_old_app_does_not_drop_a_newer_apps_stores(monkeypatch, studio_pool):
    monkeypatch.setenv("VAULT_STORE", "postgres")
    monkeypatch.setenv("PARROT_STUDIO_STORAGE", "database")
    app1, app2 = web.Application(), web.Application()
    app1["database"] = app2["database"] = studio_pool
    await backend_module.ensure_studio_storage(app1)
    await backend_module.ensure_studio_storage(app2)                # newer registration replaces app1's
    await backend_module.release_studio_stores(app1)
    assert vault_utils._PG_VAULT_STORE is not None
    await backend_module.release_studio_stores(app2)
    assert vault_utils._PG_VAULT_STORE is None


@pytest.mark.parametrize("installer", ["runtime_hooks", "studio_routes"])
async def test_cleanup_hook_is_installed_by_every_mount(installer):
    """Registration/cleanup do not depend on Studio routes: the runtime hooks (BotManager) install them too."""
    app = web.Application()
    if installer == "runtime_hooks":
        add_studio_runtime_hooks(app)
        add_studio_runtime_hooks(app)
    else:
        setup_studio_routes(app)
    assert app.on_cleanup.count(backend_module.release_studio_stores) == 1
