"""Lifecycle unit tests for the core parrot.forms package (FEAT-185).

Mirrors the parrot-formdesigner lifecycle tests but uses the simpler
core FormStorage/FormRegistry signatures.

Covers:
- FormStorage.close() default no-op (core)
- FormRegistry.__init__ with and without app (core)
- Signal registration
- on_startup / on_shutdown handlers
- Core PostgresFormStorage pool management
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from aiohttp.web import Application

from parrot.forms.registry import FormRegistry, FormStorage
from parrot.forms.storage import PostgresFormStorage


@pytest.fixture
def mock_storage():
    """Mock core FormStorage with spied initialize/close/list_forms."""
    s = AsyncMock(spec=FormStorage)
    s.initialize = AsyncMock()
    s.close = AsyncMock()
    s.list_forms = AsyncMock(return_value=[])
    return s


@pytest.fixture
def app():
    """Minimal aiohttp Application for lifecycle testing."""
    return Application()


class TestCoreFormStorageClose:
    async def test_default_close_noop(self):
        """Core FormStorage.close() default is a no-op."""
        class DummyStorage(FormStorage):
            async def save(self, form, style=None):
                return ""

            async def load(self, form_id, version=None):
                return None

            async def delete(self, form_id):
                return False

            async def list_forms(self):
                return []

        storage = DummyStorage()
        await storage.close()  # should not raise


class TestCoreFormRegistryLifecycle:
    async def test_no_app_backward_compat(self):
        """Core FormRegistry() without app still works."""
        registry = FormRegistry()
        assert len(registry) == 0

    async def test_no_app_with_storage(self, mock_storage):
        """Core FormRegistry(storage=...) without app still works."""
        registry = FormRegistry(storage=mock_storage)
        assert registry._storage is mock_storage
        assert registry._app is None

    async def test_app_self_registers(self, app, mock_storage):
        """Core FormRegistry registers itself as app['form_registry']."""
        registry = FormRegistry(app=app, storage=mock_storage)
        assert app["form_registry"] is registry

    async def test_app_signals_registered(self, app, mock_storage):
        """Core FormRegistry hooks on_startup/on_shutdown signals."""
        registry = FormRegistry(app=app, storage=mock_storage)
        startup_handlers = list(app.on_startup)
        shutdown_handlers = list(app.on_shutdown)
        assert registry.on_startup in startup_handlers
        assert registry.on_shutdown in shutdown_handlers

    async def test_on_startup_calls_initialize(self, app, mock_storage):
        """Core on_startup calls storage.initialize() when available."""
        registry = FormRegistry(app=app, storage=mock_storage)
        await registry.on_startup(app)
        mock_storage.initialize.assert_awaited_once()

    async def test_on_startup_calls_load_from_storage(self, app, mock_storage):
        """Core on_startup calls load_from_storage() after initialize()."""
        registry = FormRegistry(app=app, storage=mock_storage)
        await registry.on_startup(app)
        mock_storage.list_forms.assert_awaited_once()

    async def test_on_shutdown_calls_close(self, app, mock_storage):
        """Core on_shutdown calls storage.close()."""
        registry = FormRegistry(app=app, storage=mock_storage)
        await registry.on_shutdown(app)
        mock_storage.close.assert_awaited_once()

    async def test_on_startup_no_storage(self, app):
        """Core on_startup without storage is a no-op."""
        registry = FormRegistry(app=app)
        await registry.on_startup(app)  # should not raise

    async def test_on_shutdown_no_storage(self, app):
        """Core on_shutdown without storage is a no-op."""
        registry = FormRegistry(app=app)
        await registry.on_shutdown(app)  # should not raise


class TestCorePostgresFormStoragePool:
    def test_no_pool_construction(self):
        """Core PostgresFormStorage() constructs without pool."""
        storage = PostgresFormStorage()
        assert storage._pool is None
        assert storage._owns_pool is True

    def test_external_pool_owns_pool_false(self):
        """Core PostgresFormStorage with external pool: _owns_pool is False."""
        mock_pool = MagicMock()
        storage = PostgresFormStorage(pool=mock_pool)
        assert storage._pool is mock_pool
        assert storage._owns_pool is False

    async def test_close_self_owned_pool(self):
        """Core close() closes self-owned pool."""
        storage = PostgresFormStorage()
        mock_pool = AsyncMock()
        storage._pool = mock_pool
        storage._owns_pool = True

        await storage.close()
        mock_pool.close.assert_awaited_once()
        assert storage._pool is None

    async def test_close_external_pool_noop(self):
        """Core close() does NOT close an externally-provided pool."""
        mock_pool = AsyncMock()
        storage = PostgresFormStorage(pool=mock_pool)

        await storage.close()
        mock_pool.close.assert_not_called()
        assert storage._pool is None

    async def test_close_idempotent(self):
        """Core close() is idempotent."""
        storage = PostgresFormStorage()
        mock_pool = AsyncMock()
        storage._pool = mock_pool
        storage._owns_pool = True

        await storage.close()
        await storage.close()  # should not raise
        mock_pool.close.assert_awaited_once()  # called only once

    async def test_close_no_pool_noop(self):
        """Core close() when _pool is None is a no-op."""
        storage = PostgresFormStorage()
        assert storage._pool is None
        await storage.close()  # should not raise
