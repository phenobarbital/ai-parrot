"""Tests for PageDriver — FEAT-222 TASK-1450."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_tools.scraping.drivers.abstract import AbstractDriver
from parrot_tools.scraping.drivers.page_driver import PageDriver


@pytest.fixture
def mock_page():
    page = MagicMock()
    # Async methods.
    for name in (
        "goto", "go_back", "go_forward", "reload", "click", "fill",
        "select_option", "hover", "content", "inner_text", "get_attribute",
        "eval_on_selector_all", "screenshot", "wait_for_selector",
        "wait_for_load_state", "evaluate", "close",
    ):
        setattr(page, name, AsyncMock())
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    page.url = "https://example.com/current"
    return page


@pytest.fixture
def driver(mock_page):
    return PageDriver(mock_page)


class TestPageDriverContract:
    def test_is_abstract_driver(self, driver):
        assert isinstance(driver, AbstractDriver)

    def test_instantiable(self, mock_page):
        # All abstract methods implemented → no TypeError on construction.
        PageDriver(mock_page)


class TestLifecycle:
    async def test_start_is_noop(self, driver, mock_page):
        assert await driver.start() is None

    async def test_quit_closes_page(self, driver, mock_page):
        await driver.quit()
        mock_page.close.assert_awaited_once()


class TestNavigation:
    async def test_navigate(self, driver, mock_page):
        await driver.navigate("https://x.com", timeout=15)
        mock_page.goto.assert_awaited_once_with("https://x.com", timeout=15000)

    async def test_go_back(self, driver, mock_page):
        await driver.go_back()
        mock_page.go_back.assert_awaited_once()

    async def test_reload(self, driver, mock_page):
        await driver.reload()
        mock_page.reload.assert_awaited_once()


class TestDomInteraction:
    async def test_click(self, driver, mock_page):
        await driver.click(".btn", timeout=5)
        mock_page.click.assert_awaited_once_with(".btn", timeout=5000)

    async def test_click_xpath_prefix(self, driver, mock_page):
        await driver.click("//div[@id='x']")
        args, kwargs = mock_page.click.call_args
        assert args[0] == "xpath=//div[@id='x']"

    async def test_click_relative_xpath_prefix(self, driver, mock_page):
        await driver.click("./span")
        assert mock_page.click.call_args[0][0] == "xpath=./span"

    async def test_fill(self, driver, mock_page):
        await driver.fill("#q", "hello", timeout=8)
        mock_page.fill.assert_awaited_once_with("#q", "hello", timeout=8000)

    async def test_select_option_value(self, driver, mock_page):
        await driver.select_option("#sel", "v1", by="value")
        mock_page.select_option.assert_awaited_once_with(
            "#sel", value="v1", timeout=10000
        )

    async def test_select_option_text(self, driver, mock_page):
        await driver.select_option("#sel", "Label", by="text")
        mock_page.select_option.assert_awaited_once_with(
            "#sel", label="Label", timeout=10000
        )

    async def test_select_option_index(self, driver, mock_page):
        await driver.select_option("#sel", "2", by="index")
        mock_page.select_option.assert_awaited_once_with(
            "#sel", index=2, timeout=10000
        )

    async def test_select_option_bad_mode(self, driver):
        with pytest.raises(ValueError, match="by"):
            await driver.select_option("#sel", "x", by="nope")

    async def test_hover(self, driver, mock_page):
        await driver.hover(".item")
        mock_page.hover.assert_awaited_once_with(".item", timeout=10000)

    async def test_press_key(self, driver, mock_page):
        await driver.press_key("Enter")
        mock_page.keyboard.press.assert_awaited_once_with("Enter")


class TestContentExtraction:
    async def test_get_page_source(self, driver, mock_page):
        mock_page.content.return_value = "<html></html>"
        assert await driver.get_page_source() == "<html></html>"
        mock_page.content.assert_awaited_once()

    async def test_get_text(self, driver, mock_page):
        mock_page.inner_text.return_value = "hi"
        result = await driver.get_text(".msg", timeout=3)
        assert result == "hi"
        mock_page.inner_text.assert_awaited_once_with(".msg", timeout=3000)

    async def test_get_attribute(self, driver, mock_page):
        mock_page.get_attribute.return_value = "/link"
        result = await driver.get_attribute("a", "href")
        assert result == "/link"
        mock_page.get_attribute.assert_awaited_once_with("a", "href", timeout=10000)

    async def test_get_all_texts(self, driver, mock_page):
        mock_page.eval_on_selector_all.return_value = ["a", "b"]
        result = await driver.get_all_texts(".row")
        assert result == ["a", "b"]
        assert mock_page.eval_on_selector_all.call_args[0][0] == ".row"

    async def test_screenshot(self, driver, mock_page):
        mock_page.screenshot.return_value = b"img"
        result = await driver.screenshot("/tmp/x.png", full_page=True)
        assert result == b"img"
        mock_page.screenshot.assert_awaited_once_with(path="/tmp/x.png", full_page=True)


class TestWaiting:
    async def test_wait_for_selector(self, driver, mock_page):
        await driver.wait_for_selector(".x", timeout=4, state="attached")
        mock_page.wait_for_selector.assert_awaited_once_with(
            ".x", timeout=4000, state="attached"
        )

    async def test_wait_for_navigation(self, driver, mock_page):
        await driver.wait_for_navigation(timeout=20)
        mock_page.wait_for_load_state.assert_awaited_once_with(
            "networkidle", timeout=20000
        )

    async def test_wait_for_load_state(self, driver, mock_page):
        await driver.wait_for_load_state("domcontentloaded", timeout=12)
        mock_page.wait_for_load_state.assert_awaited_once_with(
            "domcontentloaded", timeout=12000
        )


class TestScriptsAndProperty:
    async def test_execute_script(self, driver, mock_page):
        mock_page.evaluate.return_value = 42
        result = await driver.execute_script("() => 42", 1, 2)
        assert result == 42
        mock_page.evaluate.assert_awaited_once_with("() => 42", 1, 2)

    async def test_evaluate(self, driver, mock_page):
        mock_page.evaluate.return_value = "ok"
        assert await driver.evaluate("document.title") == "ok"
        mock_page.evaluate.assert_awaited_once_with("document.title")

    def test_current_url(self, driver):
        assert driver.current_url == "https://example.com/current"
