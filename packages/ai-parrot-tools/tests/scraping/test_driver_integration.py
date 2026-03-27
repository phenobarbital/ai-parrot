"""Integration tests for the driver abstraction layer (FEAT-015).

These tests verify that all driver components — AbstractDriver, PlaywrightDriver,
SeleniumDriver, PlaywrightConfig, DriverFactory, and WebScrapingTool integration —
compose correctly as a system.

All browser backends are mocked; no real browsers are required.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from parrot.tools.scraping.drivers.abstract import AbstractDriver
from parrot.tools.scraping.driver_factory import DriverFactory


# ── Factory Lifecycle: Selenium ──────────────────────────────────


class TestFactoryLifecycleSelenium:
    """Test full lifecycle: create → start → use → quit for Selenium."""

    def test_factory_returns_abstract_driver(self):
        driver = DriverFactory.create({"driver_type": "selenium"})
        assert isinstance(driver, AbstractDriver)

    @pytest.mark.asyncio
    async def test_start_and_quit(self):
        mock_setup_cls = MagicMock()
        mock_instance = MagicMock()
        mock_wd = MagicMock()
        mock_instance.get_driver = AsyncMock(return_value=mock_wd)
        mock_setup_cls.return_value = mock_instance

        driver = DriverFactory.create({"driver_type": "selenium"})
        with patch(
            "parrot.tools.scraping.driver.SeleniumSetup", mock_setup_cls
        ):
            await driver.start()
        assert driver._driver is not None
        assert driver.current_url is not None

        await driver.quit()
        assert driver._driver is None


# ── Factory Lifecycle: Playwright ────────────────────────────────


class TestFactoryLifecyclePlaywright:
    """Test full lifecycle: create → start → use → quit for Playwright."""

    def test_factory_returns_abstract_driver(self):
        driver = DriverFactory.create({"driver_type": "playwright"})
        assert isinstance(driver, AbstractDriver)

    @pytest.mark.asyncio
    async def test_start_and_quit(self):
        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.url = "about:blank"

        mock_pw.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.set_default_timeout = MagicMock()
        mock_context.new_page.return_value = mock_page

        driver = DriverFactory.create({"driver_type": "playwright"})
        with patch(
            "playwright.async_api.async_playwright"
        ) as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)
            await driver.start()

        assert driver._page is not None
        assert driver.current_url == "about:blank"

        # Capture refs before quit nulls them
        context = driver._context
        browser = driver._browser
        playwright = driver._playwright

        await driver.quit()
        assert driver._page is None
        context.close.assert_called_once()
        browser.close.assert_called_once()
        playwright.stop.assert_called_once()


# ── Driver Swap Transparency ────────────────────────────────────


class TestDriverSwapTransparency:
    """Both drivers expose the same AbstractDriver interface."""

    @pytest.mark.parametrize("driver_type", ["selenium", "playwright"])
    def test_both_are_abstract_driver(self, driver_type):
        driver = DriverFactory.create({"driver_type": driver_type})
        assert isinstance(driver, AbstractDriver)

    @pytest.mark.parametrize("driver_type", ["selenium", "playwright"])
    def test_both_have_all_abstract_methods(self, driver_type):
        driver = DriverFactory.create({"driver_type": driver_type})
        for method_name in [
            "start", "quit", "navigate", "go_back", "go_forward", "reload",
            "click", "fill", "select_option", "hover", "press_key",
            "get_page_source", "get_text", "get_attribute", "get_all_texts",
            "screenshot", "wait_for_selector", "wait_for_navigation",
            "wait_for_load_state", "execute_script", "evaluate",
        ]:
            assert hasattr(driver, method_name), f"Missing method: {method_name}"
            assert callable(getattr(driver, method_name))

    @pytest.mark.parametrize("driver_type", ["selenium", "playwright"])
    def test_both_have_current_url_property(self, driver_type):
        driver = DriverFactory.create({"driver_type": driver_type})
        # current_url is a property on the class (may raise before start())
        assert isinstance(type(driver).__dict__.get("current_url"), property) or \
            hasattr(driver, "current_url")

    @pytest.mark.parametrize("driver_type", ["selenium", "playwright"])
    def test_both_have_extended_capabilities(self, driver_type):
        driver = DriverFactory.create({"driver_type": driver_type})
        for method_name in [
            "intercept_requests", "record_har", "save_pdf",
            "start_tracing", "stop_tracing", "mock_route",
        ]:
            assert hasattr(driver, method_name)


# ── Backward Compatibility ───────────────────────────────────────


class TestBackwardCompatibility:
    """WebScrapingTool default behavior unchanged after FEAT-015."""

    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_default_tool_uses_selenium(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_driver = MagicMock(spec=AbstractDriver)
        mock_factory.create.return_value = mock_driver

        WebScrapingTool()
        call_config = mock_factory.create.call_args[0][0]
        assert call_config["driver_type"] == "selenium"
        assert call_config["browser"] == "chrome"
        assert call_config["headless"] is True

    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_tool_still_has_driver_type_attr(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_factory.create.return_value = MagicMock(spec=AbstractDriver)
        tool = WebScrapingTool()
        assert tool.driver_type == "selenium"

    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_tool_still_has_browser_config(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_factory.create.return_value = MagicMock(spec=AbstractDriver)
        tool = WebScrapingTool(browser="firefox")
        assert tool.browser_config["browser"] == "firefox"

    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_tool_accepts_driver_config(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_factory.create.return_value = MagicMock(spec=AbstractDriver)
        WebScrapingTool(
            driver_config={"slow_mo": 200, "viewport": {"width": 800, "height": 600}}
        )
        call_config = mock_factory.create.call_args[0][0]
        assert call_config["slow_mo"] == 200
        assert call_config["viewport"] == {"width": 800, "height": 600}


# ── Public Exports ───────────────────────────────────────────────


class TestPublicExports:
    """All driver-related classes are importable from public packages."""

    def test_scraping_package_exports(self):
        from parrot.tools.scraping import (
            DriverFactory,
            AbstractDriver,
            PlaywrightDriver,
            SeleniumDriver,
            PlaywrightConfig,
        )
        assert all([
            DriverFactory, AbstractDriver, PlaywrightDriver,
            SeleniumDriver, PlaywrightConfig,
        ])

    def test_drivers_subpackage_exports(self):
        from parrot.tools.scraping.drivers import (
            AbstractDriver,
            PlaywrightConfig,
            PlaywrightDriver,
            SeleniumDriver,
        )
        assert all([AbstractDriver, PlaywrightConfig, PlaywrightDriver, SeleniumDriver])

    def test_individual_module_imports(self):
        from parrot.tools.scraping.drivers.abstract import AbstractDriver
        from parrot.tools.scraping.drivers.playwright_driver import PlaywrightDriver
        from parrot.tools.scraping.drivers.playwright_config import PlaywrightConfig
        from parrot.tools.scraping.drivers.selenium_driver import SeleniumDriver
        from parrot.tools.scraping.driver_factory import DriverFactory
        assert all([
            AbstractDriver, PlaywrightDriver, PlaywrightConfig,
            SeleniumDriver, DriverFactory,
        ])

    def test_scraping_package_all_includes_drivers(self):
        import parrot.tools.scraping as pkg
        for name in [
            "DriverFactory", "AbstractDriver", "PlaywrightDriver",
            "SeleniumDriver", "PlaywrightConfig",
        ]:
            assert name in pkg.__all__, f"{name} not in __all__"


# ── Config Round-Trip ────────────────────────────────────────────


class TestConfigRoundTrip:
    """PlaywrightConfig values survive factory creation."""

    def test_config_values_in_driver(self):
        config = {
            "driver_type": "playwright",
            "browser": "firefox",
            "headless": False,
            "slow_mo": 50,
            "locale": "fr-FR",
        }
        driver = DriverFactory.create(config)
        assert driver.config.browser_type == "firefox"
        assert driver.config.headless is False
        assert driver.config.slow_mo == 50
        assert driver.config.locale == "fr-FR"

    def test_default_config_values(self):
        driver = DriverFactory.create({"driver_type": "playwright"})
        assert driver.config.browser_type == "chromium"
        assert driver.config.headless is True
        assert driver.config.slow_mo == 0

    def test_browser_mapping_in_config(self):
        """Edge maps to chromium in PlaywrightConfig."""
        driver = DriverFactory.create({
            "driver_type": "playwright",
            "browser": "edge",
        })
        assert driver.config.browser_type == "chromium"

    def test_safari_maps_to_webkit(self):
        driver = DriverFactory.create({
            "driver_type": "playwright",
            "browser": "safari",
        })
        assert driver.config.browser_type == "webkit"

    def test_viewport_passthrough(self):
        driver = DriverFactory.create({
            "driver_type": "playwright",
            "viewport": {"width": 1024, "height": 768},
        })
        assert driver.config.viewport == {"width": 1024, "height": 768}

    def test_selenium_config_preserved(self):
        driver = DriverFactory.create({
            "driver_type": "selenium",
            "browser": "firefox",
            "headless": False,
        })
        assert driver._browser_name == "firefox"
        assert driver._headless is False
