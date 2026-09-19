"""Tests for browser executable resolution (``browser_binary`` /
``DEFAULT_CHROME_EXECUTABLE_PATH``) across the Playwright and Selenium paths.

All drivers are mocked — no real browser is launched.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.tools.scraping.driver_context import _PlaywrightSetup, _SeleniumSetupAdapter
from parrot.tools.scraping.driver_factory import DriverFactory
from parrot.tools.scraping.drivers.playwright_config import PlaywrightConfig
from parrot.tools.scraping.drivers.playwright_driver import PlaywrightDriver
from parrot.tools.scraping.toolkit_models import (
    DEFAULT_CHROME_EXECUTABLE_PATH_KEY,
    DriverConfig,
    resolve_browser_binary,
)


def _mock_playwright():
    """Return ``(async_playwright factory mock, chromium launcher mock)``."""
    context = MagicMock(new_page=AsyncMock())
    browser = MagicMock(new_context=AsyncMock(return_value=context))
    launcher = MagicMock(launch=AsyncMock(return_value=browser))
    pw = MagicMock(chromium=launcher)
    return MagicMock(start=AsyncMock(return_value=pw)), launcher


@pytest.fixture
def chrome_bin(tmp_path):
    binary = tmp_path / "google-chrome-beta"
    binary.write_text("#!/bin/sh\n")
    return str(binary)


@pytest.fixture
def default_chrome(monkeypatch, chrome_bin):
    """Point the navconfig lookup at a fake default Chrome executable."""
    from navconfig import config

    real_get = config.get

    def fake_get(key, *args, **kwargs):
        if key == DEFAULT_CHROME_EXECUTABLE_PATH_KEY:
            return chrome_bin
        return real_get(key, *args, **kwargs)

    monkeypatch.setattr(config, "get", fake_get)
    return chrome_bin


@pytest.fixture
def no_default_chrome(monkeypatch):
    from navconfig import config

    real_get = config.get

    def fake_get(key, *args, **kwargs):
        if key == DEFAULT_CHROME_EXECUTABLE_PATH_KEY:
            return None
        return real_get(key, *args, **kwargs)

    monkeypatch.setattr(config, "get", fake_get)


class TestResolveBrowserBinary:
    def test_explicit_wins_over_default(self, default_chrome):
        assert resolve_browser_binary("/usr/bin/other", "chrome") == "/usr/bin/other"

    def test_default_used_for_chrome(self, default_chrome):
        assert resolve_browser_binary(None, "chrome") == default_chrome
        assert resolve_browser_binary(None, "undetected") == default_chrome

    def test_default_used_for_chrome_channels(self, default_chrome):
        assert resolve_browser_binary(None, "chrome", "chrome") == default_chrome
        assert resolve_browser_binary(None, "chrome", "chrome-beta") == default_chrome

    def test_default_skipped_for_non_chrome_browsers(self, default_chrome):
        assert resolve_browser_binary(None, "firefox") is None
        assert resolve_browser_binary(None, "edge") is None
        assert resolve_browser_binary(None, "webkit") is None

    def test_default_skipped_for_non_chrome_channel(self, default_chrome):
        assert resolve_browser_binary(None, "chrome", "msedge") is None

    def test_missing_default_file_is_ignored(self, monkeypatch, tmp_path):
        from navconfig import config

        missing = str(tmp_path / "nope")
        monkeypatch.setattr(
            config,
            "get",
            lambda key, *a, **kw: missing if key == DEFAULT_CHROME_EXECUTABLE_PATH_KEY else None,
        )
        assert resolve_browser_binary(None, "chrome") is None

    def test_unset_default(self, no_default_chrome):
        assert resolve_browser_binary(None, "chrome") is None


class TestPlaywrightExecutablePath:
    async def test_driver_passes_executable_path_to_launch(self, chrome_bin):
        driver = PlaywrightDriver(PlaywrightConfig(channel="chrome", executable_path=chrome_bin))
        starter, launcher = _mock_playwright()
        with patch("playwright.async_api.async_playwright", return_value=starter):
            await driver.start()
        kwargs = launcher.launch.call_args.kwargs
        assert kwargs["executable_path"] == chrome_bin
        assert kwargs["channel"] == "chrome"

    async def test_driver_omits_executable_path_when_unset(self):
        driver = PlaywrightDriver(PlaywrightConfig())
        starter, launcher = _mock_playwright()
        with patch("playwright.async_api.async_playwright", return_value=starter):
            await driver.start()
        assert "executable_path" not in launcher.launch.call_args.kwargs

    async def test_setup_uses_default_chrome(self, default_chrome):
        setup = _PlaywrightSetup(DriverConfig(driver_type="playwright", browser_channel="chrome"))
        with patch(
            "parrot_tools.scraping.drivers.playwright_driver.PlaywrightDriver",
            return_value=AsyncMock(),
        ) as mock_cls:
            await setup.get_driver()
        assert mock_cls.call_args.args[0].executable_path == default_chrome

    async def test_setup_explicit_binary(self, no_default_chrome):
        setup = _PlaywrightSetup(DriverConfig(driver_type="playwright", browser_binary="/x/chrome"))
        with patch(
            "parrot_tools.scraping.drivers.playwright_driver.PlaywrightDriver",
            return_value=AsyncMock(),
        ) as mock_cls:
            await setup.get_driver()
        assert mock_cls.call_args.args[0].executable_path == "/x/chrome"

    def test_factory_forwards_binary(self, no_default_chrome):
        driver = DriverFactory.create({"driver_type": "playwright", "browser_binary": "/x/chrome"})
        assert driver.config.executable_path == "/x/chrome"


class TestSeleniumBrowserBinary:
    async def test_adapter_forwards_default_chrome(self, default_chrome):
        adapter = _SeleniumSetupAdapter(DriverConfig(driver_type="selenium"))
        with patch(
            "parrot_tools.scraping.drivers.selenium_driver.SeleniumDriver",
            return_value=AsyncMock(),
        ) as mock_cls:
            await adapter.get_driver()
        assert mock_cls.call_args.kwargs["options"]["browser_binary"] == default_chrome

    async def test_adapter_no_binary_for_firefox(self, default_chrome):
        adapter = _SeleniumSetupAdapter(DriverConfig(driver_type="selenium", browser="firefox"))
        with patch(
            "parrot_tools.scraping.drivers.selenium_driver.SeleniumDriver",
            return_value=AsyncMock(),
        ) as mock_cls:
            await adapter.get_driver()
        assert "browser_binary" not in mock_cls.call_args.kwargs["options"]

    def test_factory_forwards_binary(self, no_default_chrome):
        with patch("parrot_tools.scraping.drivers.selenium_driver.SeleniumDriver") as mock_cls:
            DriverFactory.create({"driver_type": "selenium", "browser_binary": "/x/chrome"})
        assert mock_cls.call_args.kwargs["options"]["browser_binary"] == "/x/chrome"
