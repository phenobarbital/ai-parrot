"""Integration tests for WebScrapingTool + DriverFactory (TASK-061).

Verifies that WebScrapingTool uses DriverFactory.create() for driver
creation and that backward compatibility is maintained.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from parrot.tools.scraping.drivers.abstract import AbstractDriver


# ── Default Driver ───────────────────────────────────────────────


class TestWebScrapingToolDefaultDriver:
    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_default_creates_selenium(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_driver = MagicMock(spec=AbstractDriver)
        mock_factory.create.return_value = mock_driver

        tool = WebScrapingTool()
        mock_factory.create.assert_called_once()
        call_args = mock_factory.create.call_args[0][0]
        assert call_args["driver_type"] == "selenium"
        assert call_args["browser"] == "chrome"
        assert call_args["headless"] is True


# ── Playwright Driver ────────────────────────────────────────────


class TestWebScrapingToolPlaywrightDriver:
    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_playwright_driver_type(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_driver = MagicMock(spec=AbstractDriver)
        mock_factory.create.return_value = mock_driver

        tool = WebScrapingTool(driver_type="playwright")
        call_args = mock_factory.create.call_args[0][0]
        assert call_args["driver_type"] == "playwright"


# ── Driver Config Passthrough ────────────────────────────────────


class TestWebScrapingToolDriverConfig:
    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_driver_config_passthrough(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_driver = MagicMock(spec=AbstractDriver)
        mock_factory.create.return_value = mock_driver

        tool = WebScrapingTool(
            driver_type="playwright",
            driver_config={"slow_mo": 100, "locale": "en-US"},
        )
        call_args = mock_factory.create.call_args[0][0]
        assert call_args["slow_mo"] == 100
        assert call_args["locale"] == "en-US"

    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_driver_config_overrides_defaults(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_driver = MagicMock(spec=AbstractDriver)
        mock_factory.create.return_value = mock_driver

        tool = WebScrapingTool(
            browser="chrome",
            driver_config={"browser": "firefox"},
        )
        call_args = mock_factory.create.call_args[0][0]
        # driver_config overrides the positional browser param
        assert call_args["browser"] == "firefox"


# ── Backward Compatibility ───────────────────────────────────────


class TestWebScrapingToolBackwardCompat:
    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_browser_param_forwarded(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_driver = MagicMock(spec=AbstractDriver)
        mock_factory.create.return_value = mock_driver

        tool = WebScrapingTool(browser="firefox", headless=False)
        call_args = mock_factory.create.call_args[0][0]
        assert call_args["browser"] == "firefox"
        assert call_args["headless"] is False

    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_mobile_param_forwarded(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_driver = MagicMock(spec=AbstractDriver)
        mock_factory.create.return_value = mock_driver

        tool = WebScrapingTool(mobile=True)
        call_args = mock_factory.create.call_args[0][0]
        assert call_args["mobile"] is True

    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_auto_install_param_forwarded(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_driver = MagicMock(spec=AbstractDriver)
        mock_factory.create.return_value = mock_driver

        tool = WebScrapingTool(auto_install=False)
        call_args = mock_factory.create.call_args[0][0]
        assert call_args["auto_install"] is False


# ── Initialize Driver ────────────────────────────────────────────


class TestInitializeDriver:
    @pytest.mark.asyncio
    @patch("parrot.tools.scraping.tool.DriverFactory")
    async def test_initialize_starts_abstract_driver(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_abs_driver = AsyncMock(spec=AbstractDriver)
        mock_abs_driver._driver = MagicMock()
        mock_factory.create.return_value = mock_abs_driver

        tool = WebScrapingTool()
        await tool.initialize_driver()

        mock_abs_driver.start.assert_called_once()
        assert tool.driver is mock_abs_driver._driver

    @pytest.mark.asyncio
    @patch("parrot.tools.scraping.tool.DriverFactory")
    async def test_initialize_playwright_extracts_handles(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_abs_driver = AsyncMock(spec=AbstractDriver)
        mock_abs_driver._page = MagicMock()
        mock_abs_driver._browser = MagicMock()
        mock_factory.create.return_value = mock_abs_driver

        tool = WebScrapingTool(driver_type="playwright")
        await tool.initialize_driver()

        mock_abs_driver.start.assert_called_once()
        assert tool.page is mock_abs_driver._page
        assert tool.browser is mock_abs_driver._browser


# ── Cleanup ──────────────────────────────────────────────────────


class TestCleanup:
    @pytest.mark.asyncio
    @patch("parrot.tools.scraping.tool.DriverFactory")
    async def test_cleanup_calls_abstract_driver_quit(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_abs_driver = AsyncMock(spec=AbstractDriver)
        mock_factory.create.return_value = mock_abs_driver

        tool = WebScrapingTool()
        tool.driver = MagicMock()
        await tool.cleanup()

        mock_abs_driver.quit.assert_called_once()
        assert tool.driver is None
        assert tool.page is None
        assert tool.browser is None


# ── Package Exports ──────────────────────────────────────────────


class TestScrapingPackageExports:
    def test_driver_factory_importable(self):
        from parrot.tools.scraping import DriverFactory

        assert DriverFactory is not None

    def test_abstract_driver_importable(self):
        from parrot.tools.scraping import AbstractDriver

        assert AbstractDriver is not None

    def test_playwright_driver_importable(self):
        from parrot.tools.scraping import PlaywrightDriver

        assert PlaywrightDriver is not None

    def test_selenium_driver_importable(self):
        from parrot.tools.scraping import SeleniumDriver

        assert SeleniumDriver is not None

    def test_playwright_config_importable(self):
        from parrot.tools.scraping import PlaywrightConfig

        assert PlaywrightConfig is not None
