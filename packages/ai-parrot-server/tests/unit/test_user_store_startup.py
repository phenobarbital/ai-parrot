"""FEAT-878 user-store startup validation, diagnostics, and lifecycle tests."""

import logging
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from redis.exceptions import ResponseError

from parrot.handlers.studio.storage import backend
from parrot.manager.manager import BotManager
from parrot.userstore import SWITCHES, UserStoreMisconfigured
from parrot.userstore import checks
from parrot.userstore.checks import install_user_store_hooks, run_user_store_diagnostics


@pytest.fixture(autouse=True)
def clean_user_store_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove user-store selection settings for each test."""
    for key in (
        "PARROT_USER_STORE",
        "PARROT_USER_STORE_REDIS_URL",
        "CREW_RESULT_STORAGE",
        "DOCUMENTDB_HOSTNAME",
        "DOCUMENTDB_DBNAME",
        *SWITCHES,
    ):
        monkeypatch.delenv(key, raising=False)


def test_startup_rejects_invalid_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """BotManager setup fails closed when a store switch is invalid."""
    monkeypatch.setenv("VAULT_STORE", "mongo")
    manager = BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=False)

    with pytest.raises(UserStoreMisconfigured, match="VAULT_STORE"):
        manager.setup(web.Application())


def test_guard_implicit_redis_with_documentdb(monkeypatch: pytest.MonkeyPatch) -> None:
    """The implicit Redis guard lists affected stores and both operator fixes."""
    monkeypatch.setenv("DOCUMENTDB_HOSTNAME", "documentdb.internal")

    with pytest.raises(UserStoreMisconfigured) as raised:
        install_user_store_hooks(web.Application())

    message = str(raised.value)
    assert all(switch in message for switch in SWITCHES)
    assert "CREW_RESULT_STORAGE" in message
    assert "PARROT_USER_STORE=documentdb" in message
    assert "PARROT_USER_STORE=redis" in message


@pytest.mark.asyncio
async def test_installer_idempotent_and_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Installing twice adds one hook pair whose cleanup closes the Redis client."""
    monkeypatch.setenv("PARROT_USER_STORE", "redis")
    close = AsyncMock()
    monkeypatch.setattr(checks, "close_user_store_redis", close)
    app = web.Application()
    initial_startup_count = len(app.on_startup)
    initial_cleanup_count = len(app.on_cleanup)

    install_user_store_hooks(app)
    startup_count = len(app.on_startup)
    cleanup_count = len(app.on_cleanup)
    install_user_store_hooks(app)

    assert len(app.on_startup) == startup_count == initial_startup_count + 1
    assert len(app.on_cleanup) == cleanup_count == initial_cleanup_count + 1
    await app.on_cleanup[-1](app)
    close.assert_awaited_once_with()


def test_registry_only_installs_user_store_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Registry-only hosts receive the same user-store lifecycle hooks."""
    monkeypatch.setenv("PARROT_USER_STORE", "redis")
    app = web.Application()
    manager = BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=False)

    manager.setup_registry_only(app)

    assert app["_parrot_user_store_hooks"] is True


@pytest.mark.asyncio
async def test_diagnostics_warnings_and_redacts_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Risky eviction and disabled persistence warn without exposing credentials."""
    client = AsyncMock()
    client.ping.return_value = True
    client.config_get.side_effect = [
        {"maxmemory-policy": "allkeys-lru"},
        {"appendonly": "no"},
        {"save": ""},
    ]
    monkeypatch.setattr(checks, "get_user_store_redis", lambda: client)
    monkeypatch.setenv("PARROT_USER_STORE_REDIS_URL", "redis://secret:password@redis.internal:6380/6")

    with caplog.at_level(logging.WARNING):
        warnings = await run_user_store_diagnostics()

    assert len(warnings) == 2
    assert "allkeys-lru" in warnings[0]
    assert "persistence is disabled" in warnings[1]
    assert "secret" not in caplog.text
    assert "password" not in caplog.text


@pytest.mark.asyncio
async def test_diagnostics_config_denied_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Managed Redis CONFIG denials do not warn or escape diagnostics."""
    client = AsyncMock()
    client.ping.return_value = True
    client.config_get.side_effect = ResponseError("CONFIG denied")
    monkeypatch.setattr(checks, "get_user_store_redis", lambda: client)

    assert await run_user_store_diagnostics() == []


@pytest.mark.asyncio
async def test_diagnostics_ping_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreachable Redis produces one credential-safe warning."""
    client = AsyncMock()
    client.ping.side_effect = RuntimeError("redis://secret:password@redis.internal")
    monkeypatch.setattr(checks, "get_user_store_redis", lambda: client)
    monkeypatch.setenv("PARROT_USER_STORE_REDIS_URL", "redis://secret:password@redis.internal:6380/6")

    warnings = await run_user_store_diagnostics()

    assert warnings == ["User-store Redis at redis://redis.internal:6380/6 is unreachable"]


def test_studio_postgres_switches_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-store Postgres overrides win over the global DocumentDB selection."""
    monkeypatch.setenv("PARROT_USER_STORE", "documentdb")
    monkeypatch.setenv("VAULT_STORE", "postgres")

    assert backend._postgres_switches() == ["VAULT_STORE"]
