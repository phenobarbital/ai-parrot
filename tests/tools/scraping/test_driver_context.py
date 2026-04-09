"""Tests for Driver Context Manager — TASK-050."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.tools.scraping.driver_context import (
    DriverRegistry,
    _quit_driver,
    driver_context,
)
from parrot.tools.scraping.toolkit_models import DriverConfig


class TestDriverRegistry:
    def test_selenium_registered_by_default(self):
        """Selenium driver factory is registered on module import."""
        assert "selenium" in DriverRegistry._factories

    def test_register_custom_driver(self):
        """register() adds a new driver factory."""
        factory = MagicMock()
        DriverRegistry.register("test-custom", factory)
        try:
            assert "test-custom" in DriverRegistry._factories
            assert DriverRegistry.get("test-custom") is factory
        finally:
            DriverRegistry.unregister("test-custom")

    def test_unregister(self):
        """unregister() removes a driver factory."""
        DriverRegistry.register("test-remove", MagicMock())
        DriverRegistry.unregister("test-remove")
        assert "test-remove" not in DriverRegistry._factories

    def test_unregister_nonexistent_is_safe(self):
        """unregister() on missing key does not raise."""
        DriverRegistry.unregister("does-not-exist")

    def test_get_unknown_raises(self):
        """get() raises ValueError for unregistered driver type."""
        with pytest.raises(ValueError, match="Unknown driver type"):
            DriverRegistry.get("nonexistent")

    def test_get_unknown_shows_registered(self):
        """Error message includes list of registered drivers."""
        with pytest.raises(ValueError, match="selenium"):
            DriverRegistry.get("nonexistent")

    def test_list_registered(self):
        """list_registered() returns known driver types."""
        registered = DriverRegistry.list_registered()
        assert "selenium" in registered
        assert isinstance(registered, list)

    def test_register_overwrites(self):
        """Registering the same key overwrites the previous factory."""
        factory1 = MagicMock()
        factory2 = MagicMock()
        DriverRegistry.register("test-overwrite", factory1)
        DriverRegistry.register("test-overwrite", factory2)
        try:
            assert DriverRegistry.get("test-overwrite") is factory2
        finally:
            DriverRegistry.unregister("test-overwrite")


class TestDriverContext:
    @pytest.mark.asyncio
    async def test_session_mode_yields_existing(self):
        """Session mode yields the provided driver without creating new one."""
        mock_driver = MagicMock()
        async with driver_context(DriverConfig(), session_driver=mock_driver) as d:
            assert d is mock_driver

    @pytest.mark.asyncio
    async def test_session_mode_does_not_quit(self):
        """Session mode does not quit the driver on exit."""
        mock_driver = MagicMock()
        mock_driver.quit = MagicMock()
        async with driver_context(DriverConfig(), session_driver=mock_driver):
            pass
        mock_driver.quit.assert_not_called()

    @pytest.mark.asyncio
    async def test_fresh_mode_creates_and_quits(self):
        """Fresh mode creates a new driver and quits it on exit."""
        mock_driver = MagicMock()
        mock_driver.quit = MagicMock(return_value=None)

        mock_setup = MagicMock()
        mock_setup.get_driver = AsyncMock(return_value=mock_driver)

        original = DriverRegistry._factories.get("selenium")
        DriverRegistry.register("selenium", lambda cfg: mock_setup)
        try:
            config = DriverConfig(driver_type="selenium")
            async with driver_context(config) as d:
                assert d is mock_driver
            mock_driver.quit.assert_called_once()
        finally:
            if original:
                DriverRegistry.register("selenium", original)

    @pytest.mark.asyncio
    async def test_fresh_mode_quits_on_exception(self):
        """Fresh mode quits driver even if body raises an exception."""
        mock_driver = MagicMock()
        mock_driver.quit = MagicMock(return_value=None)

        mock_setup = MagicMock()
        mock_setup.get_driver = AsyncMock(return_value=mock_driver)

        original = DriverRegistry._factories.get("selenium")
        DriverRegistry.register("selenium", lambda cfg: mock_setup)
        try:
            config = DriverConfig(driver_type="selenium")
            with pytest.raises(RuntimeError):
                async with driver_context(config):
                    raise RuntimeError("boom")
            mock_driver.quit.assert_called_once()
        finally:
            if original:
                DriverRegistry.register("selenium", original)

    @pytest.mark.asyncio
    async def test_fresh_mode_handles_async_quit(self):
        """Fresh mode handles drivers with async quit()."""
        mock_driver = AsyncMock()

        mock_setup = MagicMock()
        mock_setup.get_driver = AsyncMock(return_value=mock_driver)

        original = DriverRegistry._factories.get("selenium")
        DriverRegistry.register("selenium", lambda cfg: mock_setup)
        try:
            config = DriverConfig(driver_type="selenium")
            async with driver_context(config) as d:
                assert d is mock_driver
            mock_driver.quit.assert_awaited_once()
        finally:
            if original:
                DriverRegistry.register("selenium", original)


class TestQuitDriver:
    @pytest.mark.asyncio
    async def test_sync_quit(self):
        """_quit_driver handles sync quit() method."""
        driver = MagicMock()
        driver.quit = MagicMock(return_value=None)
        await _quit_driver(driver)
        driver.quit.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_quit(self):
        """_quit_driver handles async quit() method."""
        driver = AsyncMock()
        await _quit_driver(driver)
        driver.quit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_quit_method(self):
        """_quit_driver handles drivers without quit() method."""
        driver = object()  # no quit attribute
        await _quit_driver(driver)  # should not raise
