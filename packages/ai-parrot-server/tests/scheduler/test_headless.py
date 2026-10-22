"""Unit tests for AgentSchedulerManager headless bootstrap (TASK-2209).

Covers `start_headless()` / `stop_headless()` (no aiohttp, no real Redis or
Postgres — everything is mocked) and the `on_startup()`/`on_shutdown()`
delegation that preserves the existing aiohttp behaviour.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.scheduler.coordination import NullFireCoordinator
from parrot.scheduler.manager import AgentSchedulerManager

pytestmark = pytest.mark.requires_apscheduler


def nav_get(**overrides):
    """Stub for the shared navconfig singleton's ``get``: only ``overrides`` resolve, the rest are unset.

    ``parrot.scheduler.base`` and ``parrot.scheduler.coordination`` import the SAME navconfig singleton, so
    patching its ``get`` reaches both. A blanket ``return_value`` would therefore also answer
    ``SCHEDULER_COORDINATION`` and make ``build_fire_coordinator()`` raise.
    """

    def _get(key, *args, **kwargs):
        return overrides.get(key)

    return _get


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
        with patch.object(manager, "load_schedules_from_db", new=AsyncMock()) as mock_load:
            await manager.start_headless()

        assert manager.scheduler.running is True
        assert "default" in manager.scheduler._jobstores
        assert "redis" not in manager.scheduler._jobstores
        assert manager._pool is None
        mock_load.assert_not_awaited()

    async def test_redis_not_constructed_when_disabled(self, manager):
        with (
            patch("parrot.scheduler.base.RedisJobStore") as mock_redis_cls,
            patch.object(manager, "load_schedules_from_db", new=AsyncMock()),
        ):
            await manager.start_headless(use_redis=False)

        mock_redis_cls.assert_not_called()

    async def test_redis_jobstore_attached_when_enabled(self, manager):
        with patch.object(manager, "load_schedules_from_db", new=AsyncMock()):
            await manager.start_headless(use_redis=True)

        assert "redis" in manager.scheduler._jobstores

    async def test_register_listeners_default_true(self, manager):
        """FEAT-422: the standalone headless-daemon path (no explicit
        `register_listeners=`) must still get `define_listeners()` wired,
        per TASK-2209's original requirement."""
        with (
            patch.object(manager, "define_listeners", new=MagicMock()) as mock_define,
            patch.object(manager, "load_schedules_from_db", new=AsyncMock()),
        ):
            await manager.start_headless()

        mock_define.assert_called_once()

    async def test_register_listeners_false_skips_define_listeners(self, manager):
        """`register_listeners=False` (used by `on_startup()`) must NOT
        wire the APScheduler event listeners -- they were never called on
        the aiohttp path before FEAT-422, and this keeps it that way."""
        with (
            patch.object(manager, "define_listeners", new=MagicMock()) as mock_define,
            patch.object(manager, "load_schedules_from_db", new=AsyncMock()),
        ):
            await manager.start_headless(register_listeners=False)

        mock_define.assert_not_called()

    async def test_dsn_creates_pool_and_loads_db(self, manager):
        fake_pool = AsyncMock()
        with (
            patch("parrot.scheduler.base.AsyncDB", return_value=fake_pool) as mock_asyncdb,
            patch.object(manager, "load_schedules_from_db", new=AsyncMock()) as mock_load,
        ):
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
        with (
            patch("parrot.scheduler.base.AsyncDB", return_value=fake_pool),
            patch.object(manager, "load_schedules_from_db", new=AsyncMock()),
        ):
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
        """An unset SCHEDULER_REDIS keeps the pre-ledger-152e8ab53c60 behaviour: Redis on."""
        fake_conn = MagicMock(name="agentdb-pool")
        fake_app = {"bot_manager": None}

        with (
            patch("parrot.scheduler.base.nav_config.get", new=nav_get()),
            patch.object(manager, "start_headless", new=AsyncMock()) as mock_start,
        ):
            await manager.on_startup(fake_app, fake_conn)

        assert manager._pool is fake_conn
        mock_start.assert_awaited_once_with(use_redis=True, register_listeners=True)

    @pytest.mark.parametrize("raw", ["false", "no", "off", "0", False])
    async def test_on_startup_scheduler_redis_disabled(self, manager, raw):
        """SCHEDULER_REDIS off makes the aiohttp path start without any Redis attachment."""
        with (
            patch("parrot.scheduler.base.nav_config.get", new=nav_get(SCHEDULER_REDIS=raw)),
            patch.object(manager, "start_headless", new=AsyncMock()) as mock_start,
        ):
            await manager.on_startup({"bot_manager": None}, MagicMock(name="agentdb-pool"))

        mock_start.assert_awaited_once_with(use_redis=False, register_listeners=True)

    @pytest.mark.parametrize("raw", ["true", "yes", "on", "1", True])
    async def test_on_startup_scheduler_redis_enabled(self, manager, raw):
        with (
            patch("parrot.scheduler.base.nav_config.get", new=nav_get(SCHEDULER_REDIS=raw)),
            patch.object(manager, "start_headless", new=AsyncMock()) as mock_start,
        ):
            await manager.on_startup({"bot_manager": None}, MagicMock(name="agentdb-pool"))

        mock_start.assert_awaited_once_with(use_redis=True, register_listeners=True)

    async def test_on_startup_unrecognized_scheduler_redis_falls_back_to_enabled(self, manager):
        """A typo must not silently drop multi-worker coordination (clean_bool default)."""
        with (
            patch("parrot.scheduler.base.nav_config.get", new=nav_get(SCHEDULER_REDIS="maybe")),
            patch.object(manager, "start_headless", new=AsyncMock()) as mock_start,
        ):
            await manager.on_startup({"bot_manager": None}, MagicMock(name="agentdb-pool"))

        mock_start.assert_awaited_once_with(use_redis=True, register_listeners=True)

    async def test_on_startup_without_redis_attaches_no_redis_resources(self, manager):
        """End-to-end: SCHEDULER_REDIS=false leaves no jobstore, no client and no fire coordinator.

        The coordinator is the part that broke `backend="db"` schedules on a Redis-less install: with a
        RedisFireCoordinator active, every fire had to claim a lock first (ledger 152e8ab53c60).
        """
        with (
            patch("parrot.scheduler.base.nav_config.get", new=nav_get(SCHEDULER_REDIS="false")),
            patch("parrot.scheduler.base.RedisJobStore") as mock_redis_cls,
            patch.object(manager, "load_schedules_from_db", new=AsyncMock()),
        ):
            await manager.on_startup({"bot_manager": None}, MagicMock(name="agentdb-pool"))

        mock_redis_cls.assert_not_called()
        assert "redis" not in manager.scheduler._jobstores
        assert manager._redis_client is None
        assert isinstance(manager._fire_coordinator, NullFireCoordinator)

    async def test_on_startup_wires_listeners_end_to_end(self, manager):
        """FEAT-631 wires listeners on the real aiohttp startup path."""
        fake_conn = MagicMock(name="agentdb-pool")
        fake_app = {"bot_manager": None}

        with (
            patch.object(manager, "define_listeners", new=MagicMock()) as mock_define,
            patch.object(manager, "load_schedules_from_db", new=AsyncMock()),
        ):
            await manager.on_startup(fake_app, fake_conn)

        mock_define.assert_called_once()

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
