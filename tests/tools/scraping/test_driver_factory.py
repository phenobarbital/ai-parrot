"""Unit tests for DriverFactory (TASK-060).

All driver instantiation is mocked — no real browser is required.
"""

import pytest
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from parrot.tools.scraping.driver_factory import DriverFactory
from parrot.tools.scraping.drivers.abstract import AbstractDriver


# ── Factory Create ───────────────────────────────────────────────


class TestDriverFactoryCreate:
    @patch("parrot.tools.scraping.drivers.selenium_driver.SeleniumDriver")
    def test_default_creates_selenium(self, mock_cls):
        mock_cls.return_value = MagicMock(spec=AbstractDriver)
        driver = DriverFactory.create()
        mock_cls.assert_called_once_with(
            browser="chrome", headless=True, auto_install=True, mobile=False
        )
        assert isinstance(driver, AbstractDriver)

    @patch("parrot.tools.scraping.drivers.selenium_driver.SeleniumDriver")
    def test_selenium_explicit(self, mock_cls):
        mock_cls.return_value = MagicMock(spec=AbstractDriver)
        driver = DriverFactory.create({"driver_type": "selenium"})
        mock_cls.assert_called_once()
        assert isinstance(driver, AbstractDriver)

    @patch(
        "parrot.tools.scraping.drivers.playwright_driver.PlaywrightDriver"
    )
    @patch(
        "parrot.tools.scraping.drivers.playwright_config.PlaywrightConfig"
    )
    def test_playwright_driver_type(self, mock_config, mock_cls):
        mock_cls.return_value = MagicMock(spec=AbstractDriver)
        driver = DriverFactory.create({"driver_type": "playwright"})
        mock_config.assert_called_once()
        mock_cls.assert_called_once()
        assert isinstance(driver, AbstractDriver)

    def test_unknown_driver_type_raises(self):
        with pytest.raises(ValueError, match="Unknown driver_type"):
            DriverFactory.create({"driver_type": "puppeteer"})


# ── Browser Mapping ──────────────────────────────────────────────


class TestMapBrowserToPlaywright:
    @pytest.mark.parametrize(
        "browser,expected",
        [
            ("chrome", "chromium"),
            ("chromium", "chromium"),
            ("firefox", "firefox"),
            ("safari", "webkit"),
            ("webkit", "webkit"),
            ("edge", "chromium"),
            ("Chrome", "chromium"),
            ("FIREFOX", "firefox"),
        ],
    )
    def test_valid_mappings(self, browser, expected):
        assert DriverFactory._map_browser_to_playwright(browser) == expected

    def test_unknown_browser_raises(self):
        with pytest.raises(ValueError, match="Unknown browser"):
            DriverFactory._map_browser_to_playwright("opera")

    def test_empty_browser_raises(self):
        with pytest.raises(ValueError, match="Unknown browser"):
            DriverFactory._map_browser_to_playwright("")


# ── Dict Config ──────────────────────────────────────────────────


class TestDriverFactoryWithDict:
    @patch("parrot.tools.scraping.drivers.selenium_driver.SeleniumDriver")
    def test_dict_config_selenium(self, mock_cls):
        mock_cls.return_value = MagicMock(spec=AbstractDriver)
        DriverFactory.create({"browser": "firefox", "headless": False})
        mock_cls.assert_called_once_with(
            browser="firefox", headless=False, auto_install=True, mobile=False
        )

    @patch("parrot.tools.scraping.drivers.selenium_driver.SeleniumDriver")
    def test_dict_config_auto_install(self, mock_cls):
        mock_cls.return_value = MagicMock(spec=AbstractDriver)
        DriverFactory.create({"auto_install": False})
        mock_cls.assert_called_once_with(
            browser="chrome", headless=True, auto_install=False, mobile=False
        )


# ── Pydantic / Dataclass Config ─────────────────────────────────


class TestDriverFactoryWithModels:
    def test_pydantic_model_dump(self):
        """Config with model_dump() method is normalized to dict."""
        mock_config = MagicMock()
        mock_config.model_dump.return_value = {
            "driver_type": "selenium",
            "browser": "chrome",
            "headless": True,
        }
        driver = DriverFactory.create(mock_config)
        mock_config.model_dump.assert_called_once()
        assert isinstance(driver, AbstractDriver)

    def test_dataclass_config(self):
        """Config with __dataclass_fields__ is normalized to dict."""

        @dataclass
        class FakeConfig:
            driver_type: str = "selenium"
            browser: str = "chrome"
            headless: bool = True

        driver = DriverFactory.create(FakeConfig())
        assert isinstance(driver, AbstractDriver)


# ── Exports ──────────────────────────────────────────────────────


class TestDriverFactoryExports:
    def test_importable_from_package(self):
        from parrot.tools.scraping import DriverFactory as DF

        assert DF is DriverFactory

    def test_importable_from_module(self):
        from parrot.tools.scraping.driver_factory import (
            DriverFactory as DF,
        )

        assert DF is not None
