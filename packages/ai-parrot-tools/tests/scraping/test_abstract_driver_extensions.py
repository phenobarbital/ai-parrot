"""Tests for TASK-727: AbstractDriver.select_option(by=...) extension
and SeleniumDriver.click scroll-into-view fallback.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_tools.scraping.drivers.selenium_driver import SeleniumDriver
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver
from parrot_tools.scraping.drivers.playwright_config import PlaywrightConfig


# ── Helpers ───────────────────────────────────────────────────────────

def _make_selenium_driver() -> SeleniumDriver:
    """Return a SeleniumDriver with a mocked internal WebDriver."""
    drv = SeleniumDriver.__new__(SeleniumDriver)
    drv._driver = MagicMock()
    drv._setup = MagicMock()
    drv._browser_name = "chrome"
    drv._headless = True
    drv._auto_install = True
    drv._mobile = False
    drv._options = {}
    import logging
    drv.logger = logging.getLogger("test")
    return drv


def _make_playwright_driver() -> PlaywrightDriver:
    """Return a PlaywrightDriver with a mocked internal page."""
    drv = PlaywrightDriver.__new__(PlaywrightDriver)
    drv.config = PlaywrightConfig()
    drv._playwright = MagicMock()
    drv._browser = MagicMock()
    drv._context = MagicMock()
    drv._page = MagicMock()
    drv._responses = []
    import logging
    drv.logger = logging.getLogger("test")
    return drv


# ═══════════════════════════════════════════════════════════════════════
# SeleniumDriver._select_dispatch unit tests (internal method)
# ═══════════════════════════════════════════════════════════════════════

class TestSeleniumSelectDispatch:
    """Unit tests for SeleniumDriver._select_dispatch."""

    def test_by_value_calls_select_by_value(self):
        """_select_dispatch(by='value') calls Select.select_by_value."""
        drv = _make_selenium_driver()
        element = MagicMock()

        mock_select_cls = MagicMock()
        mock_sel = MagicMock()
        mock_select_cls.return_value = mock_sel

        with patch("selenium.webdriver.support.ui.Select", mock_select_cls):
            drv._select_dispatch(element, "opt1", "value")

        mock_sel.select_by_value.assert_called_once_with("opt1")

    def test_by_text_calls_select_by_visible_text(self):
        """_select_dispatch(by='text') calls Select.select_by_visible_text."""
        drv = _make_selenium_driver()
        element = MagicMock()

        mock_select_cls = MagicMock()
        mock_sel = MagicMock()
        mock_select_cls.return_value = mock_sel

        with patch("selenium.webdriver.support.ui.Select", mock_select_cls):
            drv._select_dispatch(element, "Foo Text", "text")

        mock_sel.select_by_visible_text.assert_called_once_with("Foo Text")

    def test_by_index_calls_select_by_index_with_int(self):
        """_select_dispatch(by='index') calls select_by_index(int(value))."""
        drv = _make_selenium_driver()
        element = MagicMock()

        mock_select_cls = MagicMock()
        mock_sel = MagicMock()
        mock_select_cls.return_value = mock_sel

        with patch("selenium.webdriver.support.ui.Select", mock_select_cls):
            drv._select_dispatch(element, "2", "index")

        mock_sel.select_by_index.assert_called_once_with(2)

    def test_unknown_by_raises_value_error(self):
        """Unknown by= mode should raise ValueError."""
        drv = _make_selenium_driver()
        element = MagicMock()

        mock_select_cls = MagicMock()
        mock_sel = MagicMock()
        mock_select_cls.return_value = mock_sel

        with patch("selenium.webdriver.support.ui.Select", mock_select_cls):
            with pytest.raises(ValueError, match="Unsupported select 'by' mode"):
                drv._select_dispatch(element, "x", "bogus")


# ═══════════════════════════════════════════════════════════════════════
# SeleniumDriver.click — scrollIntoView fallback
# ═══════════════════════════════════════════════════════════════════════

class TestSeleniumClickFallback:
    """Tests for SeleniumDriver.click scrollIntoView retry."""

    @pytest.mark.asyncio
    async def test_intercepted_click_retries_with_js(self):
        """ElementClickInterceptedException should trigger JS scroll+click."""
        from selenium.common.exceptions import ElementClickInterceptedException

        drv = _make_selenium_driver()
        element = MagicMock()
        element.click.side_effect = ElementClickInterceptedException("intercepted")

        # _run delegates to the function; we simulate run_in_executor by calling sync
        async def fake_run(func, *args, **kwargs):
            return func(*args, **kwargs)

        drv._run = fake_run

        scroll_called_with = []

        def fake_scroll(el):
            scroll_called_with.append(el)

        with patch.object(drv, "_wait_for_element", new=AsyncMock()), \
             patch.object(drv, "_find_element", return_value=element), \
             patch.object(drv, "_scroll_into_view_and_click", side_effect=fake_scroll):

            await drv.click("#btn", timeout=5)

        assert scroll_called_with == [element]

    @pytest.mark.asyncio
    async def test_not_clickable_message_retries_with_js(self):
        """WebDriverException with 'is not clickable' triggers JS fallback."""
        from selenium.common.exceptions import WebDriverException

        drv = _make_selenium_driver()
        element = MagicMock()
        element.click.side_effect = WebDriverException("element is not clickable at point")

        async def fake_run(func, *args, **kwargs):
            return func(*args, **kwargs)

        drv._run = fake_run

        scroll_called = []

        def fake_scroll(el):
            scroll_called.append(el)

        with patch.object(drv, "_wait_for_element", new=AsyncMock()), \
             patch.object(drv, "_find_element", return_value=element), \
             patch.object(drv, "_scroll_into_view_and_click", side_effect=fake_scroll):

            await drv.click("#btn", timeout=5)

        assert scroll_called == [element]

    @pytest.mark.asyncio
    async def test_other_webdriver_exception_is_reraised(self):
        """WebDriverException without 'is not clickable' should propagate."""
        from selenium.common.exceptions import WebDriverException

        drv = _make_selenium_driver()
        element = MagicMock()
        element.click.side_effect = WebDriverException("unexpected crash")

        async def fake_run(func, *args, **kwargs):
            return func(*args, **kwargs)

        drv._run = fake_run

        with patch.object(drv, "_wait_for_element", new=AsyncMock()), \
             patch.object(drv, "_find_element", return_value=element):

            with pytest.raises(WebDriverException, match="unexpected crash"):
                await drv.click("#btn", timeout=5)

    def test_scroll_into_view_and_click_calls_execute_script(self):
        """_scroll_into_view_and_click must call driver.execute_script."""
        drv = _make_selenium_driver()
        element = MagicMock()

        drv._scroll_into_view_and_click(element)

        drv._driver.execute_script.assert_called_once()
        script_arg = drv._driver.execute_script.call_args[0][0]
        assert "scrollIntoView" in script_arg
        assert "click" in script_arg


# ═══════════════════════════════════════════════════════════════════════
# PlaywrightDriver.select_option — extended dispatch tests
# ═══════════════════════════════════════════════════════════════════════

class TestPlaywrightSelectOption:
    """Tests for extended PlaywrightDriver.select_option(by=...)."""

    @pytest.mark.asyncio
    async def test_by_value_calls_select_option_with_value_kwarg(self):
        """by='value' should call locator.select_option(value=..., timeout=...)."""
        drv = _make_playwright_driver()

        mock_locator = AsyncMock()
        drv._page.locator = MagicMock(return_value=mock_locator)

        await drv.select_option("#sel", "v1", by="value", timeout=5)

        mock_locator.select_option.assert_awaited_once_with(value="v1", timeout=5000)

    @pytest.mark.asyncio
    async def test_by_text_calls_select_option_with_label_kwarg(self):
        """by='text' should call locator.select_option(label=..., timeout=...)."""
        drv = _make_playwright_driver()

        mock_locator = AsyncMock()
        drv._page.locator = MagicMock(return_value=mock_locator)

        await drv.select_option("#sel", "Foo Label", by="text", timeout=10)

        mock_locator.select_option.assert_awaited_once_with(label="Foo Label", timeout=10000)

    @pytest.mark.asyncio
    async def test_by_index_calls_select_option_with_index_kwarg(self):
        """by='index' should call locator.select_option(index=int(...), timeout=...)."""
        drv = _make_playwright_driver()

        mock_locator = AsyncMock()
        drv._page.locator = MagicMock(return_value=mock_locator)

        await drv.select_option("#sel", "3", by="index", timeout=10)

        mock_locator.select_option.assert_awaited_once_with(index=3, timeout=10000)

    @pytest.mark.asyncio
    async def test_unknown_by_raises_value_error(self):
        """Unknown by= mode should raise ValueError."""
        drv = _make_playwright_driver()

        mock_locator = AsyncMock()
        drv._page.locator = MagicMock(return_value=mock_locator)

        with pytest.raises(ValueError, match="Unsupported select 'by' mode"):
            await drv.select_option("#sel", "x", by="bogus")

    @pytest.mark.asyncio
    async def test_default_by_is_value(self):
        """No by= kwarg should default to value-based selection."""
        drv = _make_playwright_driver()

        mock_locator = AsyncMock()
        drv._page.locator = MagicMock(return_value=mock_locator)

        await drv.select_option("#sel", "v2")

        mock_locator.select_option.assert_awaited_once_with(value="v2", timeout=10000)
