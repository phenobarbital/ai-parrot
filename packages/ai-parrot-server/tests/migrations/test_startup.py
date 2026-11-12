"""Database-bot startup wiring for bounded migration diagnostics."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

import parrot.manager.manager as manager_module
import parrot.migrations.startup as startup_module
from parrot.manager.manager import BotManager
from parrot.migrations.models import MigrationReport


def _manager(*, enabled: bool) -> BotManager:
    """Create a manager with unrelated startup paths disabled."""
    return BotManager(enable_database_bots=enabled, enable_registry_bots=False, enable_crews=False)


@pytest.mark.asyncio
async def test_disabled_database_bots_never_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip both the probe and frozen loader when database bots are disabled."""
    probe = AsyncMock()
    monkeypatch.setattr(startup_module, "warn_pending_migrations", probe)
    manager = _manager(enabled=False)
    manager._load_database_bots = AsyncMock()

    await manager.load_bots(object())

    probe.assert_not_awaited()
    manager._load_database_bots.assert_not_awaited()


@pytest.mark.asyncio
async def test_enabled_probe_precedes_unchanged_loader_and_uses_runtime_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probe the runtime DSN immediately before invoking the existing loader."""
    calls: list[str] = []
    runtime_dsn = "postgresql://configured-runtime"
    probe = AsyncMock(side_effect=lambda *args, **kwargs: calls.append("probe"))
    loader = AsyncMock(side_effect=lambda app: calls.append("loader"))
    monkeypatch.setattr(startup_module, "warn_pending_migrations", probe)
    monkeypatch.setattr(manager_module, "default_dsn", runtime_dsn)
    manager = _manager(enabled=True)
    manager._load_database_bots = loader
    app = object()

    await manager.load_bots(app)

    assert calls == ["probe", "loader"]
    probe.assert_awaited_once_with(runtime_dsn, logger=manager.logger)
    loader.assert_awaited_once_with(app)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError(), RuntimeError("postgresql://user:secret@host/db SELECT private")])
async def test_timeout_or_failure_still_loads_database_bots(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    """Let the bounded helper sanitize failures while startup continues."""
    monkeypatch.setattr(manager_module, "default_dsn", "postgresql://runtime")
    monkeypatch.setattr("parrot.migrations.checks.status", AsyncMock(side_effect=failure))
    manager = _manager(enabled=True)
    manager._load_database_bots = AsyncMock()

    await manager.load_bots(object())

    manager._load_database_bots.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_propagates_without_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserve cancellation and do not enter the database-bot loader afterward."""
    monkeypatch.setattr(manager_module, "default_dsn", "postgresql://runtime")
    monkeypatch.setattr("parrot.migrations.checks.status", AsyncMock(side_effect=asyncio.CancelledError))
    manager = _manager(enabled=True)
    manager._load_database_bots = AsyncMock()

    with pytest.raises(asyncio.CancelledError):
        await manager.load_bots(object())

    manager._load_database_bots.assert_not_awaited()


@pytest.mark.asyncio
async def test_enabled_probe_uses_configured_bots_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """Select the configured bots migration target through the real startup helper."""
    report = MigrationReport(items=[], applied=[], failed=[], skipped=[], diagnostics=[], exit_code=0)
    status = AsyncMock(return_value=report)
    monkeypatch.setattr(manager_module, "default_dsn", "postgresql://runtime")
    monkeypatch.setattr("parrot.migrations.checks.status", status)
    manager = _manager(enabled=True)
    manager._load_database_bots = AsyncMock()

    await manager.load_bots(object())

    _, kwargs = status.await_args
    assert kwargs["sets"][0].name == "bots"
    assert kwargs["sets"][0].tables == ("navigator.ai_bots",)
