"""Lifecycle unit tests for FormRegistry + FormStorage (FEAT-185).

Covers:
- FormStorage.close() default no-op
- FormRegistry.__init__ with and without app
- aiohttp signal registration (on_startup / on_shutdown)
- on_startup calls storage.initialize() + load_from_storage()
- on_shutdown calls storage.close()
- Backward compatibility: FormRegistry() without app still works
"""

import pytest
from unittest.mock import AsyncMock
from aiohttp.web import Application

from parrot_formdesigner.services.registry import FormRegistry, FormStorage


@pytest.fixture
def mock_storage():
    """Mock FormStorage with spied initialize/close/list_forms."""
    s = AsyncMock(spec=FormStorage)
    s.initialize = AsyncMock()
    s.close = AsyncMock()
    s.list_forms = AsyncMock(return_value=[])
    return s


@pytest.fixture
def app():
    """Minimal aiohttp Application for lifecycle testing."""
    return Application()


class TestFormStorageClose:
    async def test_default_close_noop(self):
        """A concrete subclass that inherits close() should not raise."""
        class DummyStorage(FormStorage):
            async def save(self, form, style=None, *, tenant=None):
                return ""

            async def load(self, form_id, version=None, *, tenant=None):
                return None

            async def delete(self, form_id, *, tenant=None):
                return False

            async def list_forms(self, *, tenant=None):
                return []

        storage = DummyStorage()
        # Should not raise — default implementation is a no-op.
        await storage.close()


class TestFormRegistryLifecycle:
    async def test_no_app_backward_compat(self):
        """FormRegistry() without app still works (backward compatibility)."""
        registry = FormRegistry()
        assert len(registry) == 0
        assert registry.has_storage is False

    async def test_no_app_with_storage(self, mock_storage):
        """FormRegistry(storage=...) without app still works."""
        registry = FormRegistry(storage=mock_storage)
        assert registry.has_storage is True
        assert registry._app is None

    async def test_app_self_registers(self, app, mock_storage):
        """FormRegistry(app=app, storage=...) stores itself as app['form_registry']."""
        registry = FormRegistry(app=app, storage=mock_storage)
        assert app["form_registry"] is registry

    async def test_app_signals_registered(self, app, mock_storage):
        """on_startup and on_shutdown are appended to app signals."""
        registry = FormRegistry(app=app, storage=mock_storage)
        # aiohttp stores signals as lists of coroutine functions
        startup_handlers = list(app.on_startup)
        shutdown_handlers = list(app.on_shutdown)
        assert registry.on_startup in startup_handlers
        assert registry.on_shutdown in shutdown_handlers

    async def test_on_startup_calls_initialize(self, app, mock_storage):
        """on_startup calls storage.initialize() when the method exists."""
        registry = FormRegistry(app=app, storage=mock_storage)
        await registry.on_startup(app)
        mock_storage.initialize.assert_awaited_once()

    async def test_on_startup_calls_load_from_storage(self, app, mock_storage):
        """on_startup calls load_from_storage() after initialize()."""
        registry = FormRegistry(app=app, storage=mock_storage)
        await registry.on_startup(app)
        mock_storage.list_forms.assert_awaited_once()

    async def test_on_shutdown_calls_close(self, app, mock_storage):
        """on_shutdown calls storage.close()."""
        registry = FormRegistry(app=app, storage=mock_storage)
        await registry.on_shutdown(app)
        mock_storage.close.assert_awaited_once()

    async def test_on_startup_no_storage(self, app):
        """on_startup without storage configured is a no-op (no error)."""
        registry = FormRegistry(app=app)
        # Should not raise
        await registry.on_startup(app)

    async def test_on_shutdown_no_storage(self, app):
        """on_shutdown without storage configured is a no-op (no error)."""
        registry = FormRegistry(app=app)
        # Should not raise
        await registry.on_shutdown(app)

    async def test_on_startup_no_initialize_method(self, app):
        """on_startup skips initialize() if storage has no such method."""
        class StorageWithoutInit(FormStorage):
            async def save(self, form, style=None, *, tenant=None):
                return ""

            async def load(self, form_id, version=None, *, tenant=None):
                return None

            async def delete(self, form_id, *, tenant=None):
                return False

            async def list_forms(self, *, tenant=None):
                return []

        storage = StorageWithoutInit()
        registry = FormRegistry(app=app, storage=storage)
        # Should not raise even though initialize() is absent
        await registry.on_startup(app)

    async def test_no_app_no_signal_side_effects(self, mock_storage):
        """FormRegistry without app must NOT modify app state."""
        registry = FormRegistry(storage=mock_storage)
        assert registry._app is None
        # Signals not registered — nothing to verify beyond no exception
