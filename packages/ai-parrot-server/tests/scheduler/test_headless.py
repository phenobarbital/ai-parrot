"""Unit tests for AgentSchedulerManager headless bootstrap (TASK-2209).

Covers `start_headless()` / `stop_headless()` (no aiohttp, no real Redis or
Postgres — everything is mocked) and the `on_startup()`/`on_shutdown()`
delegation that preserves the existing aiohttp behaviour.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.scheduler.manager import AgentSchedulerManager

pytestmark = pytest.mark.requires_apscheduler


@pytest.fixture
async def manager():
    mgr = AgentSchedulerManager()
    yield mgr
    # Best-effort cleanup so the AsyncIOScheduler doesn't leak across tests.
    # Async fixture: teardown still runs on the test's own event loop
    # (unlike a plain-sync fixture, whose teardown would run after the
    # loop closes and blow up on AsyncIOScheduler's call_soon_threadsafe).
    await mgr.stop_headless(wait=False)


class TestStartHeadless:
    async def test_no_dsn_no_redis_memory_jobstore(self, manager):
        with patch.object(
            manager, "load_schedules_from_db", new=AsyncMock()
        ) as mock_load:
            await manager.start_headless()

        assert manager.scheduler.running is True
        assert "default" in manager.scheduler._jobstores
        assert "redis" not in manager.scheduler._jobstores
        assert manager._pool is None
        mock_load.assert_not_awaited()

    async def test_redis_not_constructed_when_disabled(self, manager):
        with patch(
            "parrot.scheduler.manager.RedisJobStore"
        ) as mock_redis_cls, patch.object(
            manager, "load_schedules_from_db", new=AsyncMock()
        ):
            await manager.start_headless(use_redis=False)

        mock_redis_cls.assert_not_called()

    async def test_redis_jobstore_attached_when_enabled(self, manager):
        with patch.object(manager, "load_schedules_from_db", new=AsyncMock()):
            await manager.start_headless(use_redis=True)

        assert "redis" in manager.scheduler._jobstores

    async def test_dsn_creates_pool_and_loads_db(self, manager):
        fake_pool = AsyncMock()
        with patch(
            "parrot.scheduler.manager.AsyncDB", return_value=fake_pool
        ) as mock_asyncdb, patch.object(
            manager, "load_schedules_from_db", new=AsyncMock()
        ) as mock_load:
            await manager.start_headless(dsn="postgres://fake")

        mock_asyncdb.assert_called_once_with("pg", dsn="postgres://fake")
        fake_pool.connection.assert_awaited_once()
        assert manager._pool is fake_pool
        assert manager._owns_pool is True
        mock_load.assert_awaited_once()

    async def test_stop_headless_partial_init(self, manager):
        # start_headless() was never called -- must not raise.
        await manager.stop_headless()
        assert manager._pool is None

    async def test_stop_headless_closes_owned_pool(self, manager):
        fake_pool = AsyncMock()
        with patch(
            "parrot.scheduler.manager.AsyncDB", return_value=fake_pool
        ), patch.object(manager, "load_schedules_from_db", new=AsyncMock()):
            await manager.start_headless(dsn="postgres://fake")

        await manager.stop_headless()
        # AsyncIOScheduler.shutdown() dispatches the actual state change via
        # call_soon_threadsafe -- give the loop one tick to process it.
        await asyncio.sleep(0)

        fake_pool.close.assert_awaited_once()
        assert manager._pool is None
        assert manager._owns_pool is False
        assert manager.scheduler.running is False


class TestAiohttpDelegation:
    async def test_on_startup_delegates(self, manager):
        fake_conn = MagicMock(name="agentdb-pool")
        fake_app = {"bot_manager": None}

        with patch.object(
            manager, "start_headless", new=AsyncMock()
        ) as mock_start:
            await manager.on_startup(fake_app, fake_conn)

        assert manager._pool is fake_conn
        mock_start.assert_awaited_once_with(use_redis=True)

    async def test_on_shutdown_preserves_injected_pool(self, manager):
        """A pool injected via on_startup()/conn is NOT owned -- on_shutdown
        must not attempt to close it (zero behaviour change vs. before the
        refactor, where on_shutdown never touched the pool at all)."""
        fake_conn = MagicMock(name="agentdb-pool")
        manager._pool = fake_conn
        manager._owns_pool = False

        with patch.object(manager, "load_schedules_from_db", new=AsyncMock()):
            await manager.start_headless(use_redis=False)

        await manager.on_shutdown({}, fake_conn)
        # AsyncIOScheduler.shutdown() dispatches the actual state change via
        # call_soon_threadsafe -- give the loop one tick to process it.
        await asyncio.sleep(0)

        fake_conn.close.assert_not_called()
        assert manager._pool is fake_conn
        assert manager.scheduler.running is False

    async def test_register_bot_schedules_after_headless_start(self, manager):
        """register_bot_schedules() should keep working after a headless
        start (no aiohttp involved) -- exercised with a fake bot exposing no
        decorated methods, so we only assert it runs without error and
        returns zero registrations."""
        with patch.object(manager, "load_schedules_from_db", new=AsyncMock()):
            await manager.start_headless()

        class _FakeBot:
            pass

        count = manager.register_bot_schedules(_FakeBot())
        assert count == 0
