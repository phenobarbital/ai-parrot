"""Typing and element screenshot contract tests across browser backends."""

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_tools.scraping.drivers.abstract import AbstractDriver
from parrot_tools.scraping.drivers.page_driver import PageDriver
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver
from parrot_tools.scraping.drivers.selenium_driver import SeleniumDriver


def _old_driver_class() -> type[AbstractDriver]:
    """Create a concrete pre-capability driver without the new methods."""

    async def noop(*args: Any, **kwargs: Any) -> None:
        """Implement an asynchronous abstract method for this test."""

    async def empty_text(*args: Any, **kwargs: Any) -> str:
        """Implement a text-returning abstract method for this test."""
        return ""

    async def empty_list(*args: Any, **kwargs: Any) -> list[str]:
        """Implement a list-returning abstract method for this test."""
        return []

    async def optional_text(*args: Any, **kwargs: Any) -> Optional[str]:
        """Implement an optional text-returning abstract method for this test."""
        return None

    async def empty_bytes(*args: Any, **kwargs: Any) -> bytes:
        """Implement a bytes-returning abstract method for this test."""
        return b""

    methods: Dict[str, Any] = {
        "start": noop,
        "quit": noop,
        "navigate": noop,
        "go_back": noop,
        "go_forward": noop,
        "reload": noop,
        "click": noop,
        "fill": noop,
        "select_option": noop,
        "hover": noop,
        "press_key": noop,
        "get_page_source": empty_text,
        "get_text": empty_text,
        "get_attribute": optional_text,
        "get_all_texts": empty_list,
        "screenshot": empty_bytes,
        "wait_for_selector": noop,
        "wait_for_navigation": noop,
        "wait_for_load_state": noop,
        "execute_script": noop,
        "evaluate": noop,
        "current_url": property(lambda self: "about:blank"),
    }
    return type("OldDriver", (AbstractDriver,), methods)


@pytest.mark.parametrize("driver_class", [PlaywrightDriver, PageDriver])
async def test_playwright_type_text_with_selector(driver_class: Any) -> None:
    """Both Playwright adapters clear and type with converted timeout."""
    locator = MagicMock()
    locator.fill = AsyncMock()
    locator.press_sequentially = AsyncMock()
    page = MagicMock()
    page.locator = MagicMock(return_value=locator)
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    driver = driver_class(page) if driver_class is PageDriver else driver_class()
    if driver_class is PlaywrightDriver:
        driver._page = page

    await driver.type_text("hello", selector="//input", delay_ms=12, clear_first=True, timeout=4)

    page.locator.assert_called_once_with("xpath=//input")
    locator.fill.assert_awaited_once_with("")
    locator.press_sequentially.assert_awaited_once_with("hello", delay=12, timeout=4000)


@pytest.mark.parametrize("driver_class", [PlaywrightDriver, PageDriver])
async def test_playwright_type_text_focused_does_not_clear(driver_class: Any) -> None:
    """Focused typing never clears an unspecified target."""
    page = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.locator = MagicMock()
    driver = driver_class(page) if driver_class is PageDriver else driver_class()
    if driver_class is PlaywrightDriver:
        driver._page = page

    await driver.type_text("hello", clear_first=True, delay_ms=7)

    page.keyboard.type.assert_awaited_once_with("hello", delay=7)
    page.locator.assert_not_called()


@pytest.mark.parametrize("driver_class", [PlaywrightDriver, PageDriver])
@pytest.mark.parametrize("selector", [".avatar", "./img"])
async def test_playwright_screenshot_element_resolves_selector(driver_class: Any, selector: str) -> None:
    """Both Playwright adapters capture CSS and XPath element PNGs."""
    locator = MagicMock()
    locator.screenshot = AsyncMock(return_value=b"png")
    page = MagicMock()
    page.locator = MagicMock(return_value=locator)
    driver = driver_class(page) if driver_class is PageDriver else driver_class()
    if driver_class is PlaywrightDriver:
        driver._page = page

    result = await driver.screenshot_element(selector, "/tmp/element.png", timeout=3)

    expected_selector = "xpath=./img" if selector.startswith("./") else selector
    page.locator.assert_called_once_with(expected_selector)
    locator.screenshot.assert_awaited_once_with(path="/tmp/element.png", timeout=3000)
    assert result == b"png"


@pytest.mark.parametrize("driver_class", [PlaywrightDriver, PageDriver])
async def test_playwright_type_text_propagates_locator_errors(driver_class: Any) -> None:
    """Playwright adapter failures retain the locator exception."""
    locator = MagicMock()
    locator.fill = AsyncMock()
    locator.press_sequentially = AsyncMock(side_effect=RuntimeError("typing failed"))
    page = MagicMock()
    page.locator = MagicMock(return_value=locator)
    driver = driver_class(page) if driver_class is PageDriver else driver_class()
    if driver_class is PlaywrightDriver:
        driver._page = page

    with pytest.raises(RuntimeError, match="typing failed"):
        await driver.type_text("hello", selector="#target")


async def test_abstract_driver_defaults_raise() -> None:
    """An old concrete subclass rejects optional capabilities without becoming abstract."""
    driver = _old_driver_class()()

    with pytest.raises(NotImplementedError, match="type_text"):
        await driver.type_text("hello")
    with pytest.raises(NotImplementedError, match="screenshot_element"):
        await driver.screenshot_element("#target", "/tmp/element.png")


async def test_selenium_type_text_and_screenshot_element(tmp_path: Path) -> None:
    """Selenium writes element bytes and bridges selected typing operations."""
    driver = SeleniumDriver()
    element = MagicMock()
    element.screenshot_as_png = b"element-png"
    driver._find_element = MagicMock(return_value=element)
    driver._wait_for_element = AsyncMock()

    await driver.type_text("hello", selector="#target", clear_first=True, timeout=2)
    output_path = tmp_path / "element.png"
    result = await driver.screenshot_element("#target", str(output_path), timeout=3)

    driver._wait_for_element.assert_any_await("#target", 2)
    driver._wait_for_element.assert_any_await("#target", 3)
    assert driver._find_element.call_args_list[0].args == ("#target",)
    element.clear.assert_called_once()
    element.send_keys.assert_called_once_with("hello")
    assert result == b"element-png"
    assert output_path.read_bytes() == b"element-png"


async def test_selenium_focused_typing_paces_without_trailing_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Focused Selenium typing sends individual keys with only inter-key delays."""
    driver = SeleniumDriver()
    focused_element = MagicMock()
    webdriver = MagicMock()
    webdriver.switch_to.active_element = focused_element
    driver._driver = webdriver
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    await driver.type_text("ab", delay_ms=25, clear_first=True)

    assert focused_element.send_keys.call_args_list[0].args == ("a",)
    assert focused_element.send_keys.call_args_list[1].args == ("b",)
    sleep.assert_awaited_once_with(0.025)


async def test_selenium_full_page_screenshot_logs_viewport_notice(caplog: pytest.LogCaptureFixture) -> None:
    """Selenium preserves viewport screenshots when full-page capture is requested."""
    driver = SeleniumDriver()
    driver._driver = MagicMock()
    driver._driver.get_screenshot_as_png.return_value = b"png"

    with caplog.at_level("DEBUG"):
        result = await driver.screenshot("/tmp/viewport.png", full_page=True)

    assert result == b"png"
    assert "viewport" in caplog.text
