"""Unit tests for parrot_tools.computer.backend (TASK-1476)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_tools.computer.backend import AsyncComputerBackend, _normalize_key
from parrot_tools.computer.models import EnvState


@pytest.fixture
def mock_page():
    """Mock Playwright page with screenshot, mouse, keyboard, and navigation methods."""
    page = AsyncMock()
    page.screenshot.return_value = b"\x89PNG\r\n\x1a\n"
    page.url = "https://example.com"
    page.viewport_size = {"width": 1280, "height": 720}
    page.wait_for_load_state = AsyncMock()
    page.mouse = AsyncMock()
    page.keyboard = AsyncMock()
    page.video = None
    return page


@pytest.fixture
def backend(mock_page):
    """AsyncComputerBackend with mocked page (no browser required)."""
    b = AsyncComputerBackend(viewport=(1280, 720))
    b._page = mock_page
    return b


class TestKeyNormalization:
    """Tests for _normalize_key()."""

    def test_control(self):
        assert _normalize_key("control") == "ControlOrMeta"

    def test_ctrl(self):
        assert _normalize_key("ctrl") == "ControlOrMeta"

    def test_shift(self):
        assert _normalize_key("shift") == "Shift"

    def test_enter(self):
        assert _normalize_key("enter") == "Enter"

    def test_esc(self):
        assert _normalize_key("esc") == "Escape"

    def test_unknown_passthrough(self):
        assert _normalize_key("SomeKey") == "SomeKey"

    def test_case_insensitive(self):
        assert _normalize_key("ENTER") == "Enter"
        assert _normalize_key("Shift") == "Shift"


class TestAsyncComputerBackend:
    """Tests for AsyncComputerBackend action methods."""

    def test_screen_size_default(self):
        b = AsyncComputerBackend()
        assert b.screen_size() == (1280, 720)

    def test_screen_size_custom(self):
        b = AsyncComputerBackend(viewport=(1920, 1080))
        assert b.screen_size() == (1920, 1080)

    @pytest.mark.asyncio
    async def test_click_at(self, backend, mock_page):
        result = await backend.click_at(640, 360)
        assert isinstance(result, EnvState)
        mock_page.mouse.click.assert_called_once_with(640, 360)

    @pytest.mark.asyncio
    async def test_hover_at(self, backend, mock_page):
        result = await backend.hover_at(100, 200)
        assert isinstance(result, EnvState)
        mock_page.mouse.move.assert_called_once_with(100, 200)

    @pytest.mark.asyncio
    async def test_type_text_at_basic(self, backend, mock_page):
        result = await backend.type_text_at(100, 200, "hello")
        assert isinstance(result, EnvState)
        mock_page.mouse.click.assert_called_once_with(100, 200)
        mock_page.keyboard.type.assert_called_once_with("hello")

    @pytest.mark.asyncio
    async def test_type_text_at_with_enter(self, backend, mock_page):
        result = await backend.type_text_at(100, 200, "hello", press_enter=True)
        assert isinstance(result, EnvState)
        mock_page.keyboard.press.assert_any_call("Enter")

    @pytest.mark.asyncio
    async def test_type_text_at_clear_before(self, backend, mock_page):
        result = await backend.type_text_at(100, 200, "hello", clear_before_typing=True)
        assert isinstance(result, EnvState)
        mock_page.keyboard.press.assert_any_call("ControlOrMeta+a")

    @pytest.mark.asyncio
    async def test_type_text_at_no_clear(self, backend, mock_page):
        mock_page.keyboard.press.reset_mock()
        await backend.type_text_at(100, 200, "hello", clear_before_typing=False)
        # ControlOrMeta+a should NOT have been called
        calls = [str(c) for c in mock_page.keyboard.press.call_args_list]
        assert not any("ControlOrMeta+a" in c for c in calls)

    @pytest.mark.asyncio
    async def test_scroll_document_down(self, backend, mock_page):
        mock_page.evaluate = AsyncMock()
        result = await backend.scroll_document("down")
        assert isinstance(result, EnvState)
        mock_page.evaluate.assert_called_once_with("window.scrollBy(0, 800)")

    @pytest.mark.asyncio
    async def test_scroll_document_up(self, backend, mock_page):
        mock_page.evaluate = AsyncMock()
        result = await backend.scroll_document("up")
        assert isinstance(result, EnvState)
        mock_page.evaluate.assert_called_once_with("window.scrollBy(0, -800)")

    @pytest.mark.asyncio
    async def test_scroll_at(self, backend, mock_page):
        result = await backend.scroll_at(640, 360, "down", magnitude=500)
        assert isinstance(result, EnvState)
        mock_page.mouse.move.assert_called_with(640, 360)
        mock_page.mouse.wheel.assert_called_once_with(0, 500)

    @pytest.mark.asyncio
    async def test_wait_seconds(self, backend, mock_page):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await backend.wait_seconds(2)
            assert isinstance(result, EnvState)
            # asyncio.sleep called once for wait_seconds(2) + once inside current_state
            assert mock_sleep.call_count >= 1

    @pytest.mark.asyncio
    async def test_go_back(self, backend, mock_page):
        mock_page.go_back = AsyncMock()
        result = await backend.go_back()
        assert isinstance(result, EnvState)
        mock_page.go_back.assert_called_once()

    @pytest.mark.asyncio
    async def test_go_forward(self, backend, mock_page):
        mock_page.go_forward = AsyncMock()
        result = await backend.go_forward()
        assert isinstance(result, EnvState)
        mock_page.go_forward.assert_called_once()

    @pytest.mark.asyncio
    async def test_search(self, backend, mock_page):
        mock_page.goto = AsyncMock()
        result = await backend.search()
        assert isinstance(result, EnvState)
        mock_page.goto.assert_called_with("https://www.google.com")

    @pytest.mark.asyncio
    async def test_navigate(self, backend, mock_page):
        mock_page.goto = AsyncMock()
        result = await backend.navigate("https://news.ycombinator.com")
        assert isinstance(result, EnvState)
        mock_page.goto.assert_called_with("https://news.ycombinator.com")

    @pytest.mark.asyncio
    async def test_key_combination(self, backend, mock_page):
        result = await backend.key_combination(["control", "c"])
        assert isinstance(result, EnvState)
        mock_page.keyboard.press.assert_called_with("ControlOrMeta+c")

    @pytest.mark.asyncio
    async def test_drag_and_drop(self, backend, mock_page):
        result = await backend.drag_and_drop(100, 100, 400, 400)
        assert isinstance(result, EnvState)
        mock_page.mouse.move.assert_any_call(100, 100)
        mock_page.mouse.down.assert_called_once()
        mock_page.mouse.up.assert_called_once()

    @pytest.mark.asyncio
    async def test_open_web_browser(self, backend, mock_page):
        mock_page.goto = AsyncMock()
        result = await backend.open_web_browser()
        assert isinstance(result, EnvState)
        mock_page.goto.assert_called_with("https://www.google.com")

    @pytest.mark.asyncio
    async def test_screenshot_returns_bytes(self, backend, mock_page):
        result = await backend.screenshot()
        assert isinstance(result, bytes)
        mock_page.screenshot.assert_called_with(full_page=False)

    @pytest.mark.asyncio
    async def test_screenshot_full_page(self, backend, mock_page):
        await backend.screenshot(full_page=True)
        mock_page.screenshot.assert_called_with(full_page=True)

    @pytest.mark.asyncio
    async def test_current_state(self, backend, mock_page):
        result = await backend.current_state()
        assert isinstance(result, EnvState)
        assert result.url == "https://example.com"
        assert result.screenshot == b"\x89PNG\r\n\x1a\n"
