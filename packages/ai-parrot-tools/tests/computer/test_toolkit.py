"""Unit tests for parrot_tools.computer.toolkit (TASK-1477)."""
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_tools.computer.models import EnvState
from parrot_tools.computer.toolkit import ComputerInteractionToolkit


@pytest.fixture
def toolkit():
    """ComputerInteractionToolkit with mocked backend (browser not launched)."""
    tk = ComputerInteractionToolkit(viewport=(1280, 720), headless=True)
    # Use AsyncMock for async methods; MagicMock for sync methods
    tk._backend = AsyncMock()
    # screen_size() is synchronous — use MagicMock so it returns immediately
    tk._backend.screen_size = MagicMock(return_value=(1280, 720))
    tk._backend._page = MagicMock()
    tk._backend._page.url = "https://example.com"
    tk._started = True  # Skip lazy start
    return tk


def _env_state(url: str = "https://example.com") -> EnvState:
    return EnvState(screenshot=b"\x89PNG", url=url)


class TestToolDiscovery:
    """Tests for tool auto-discovery and naming."""

    def test_tool_prefix(self, toolkit):
        tools = toolkit.get_tools()
        for tool in tools:
            assert tool.name.startswith("computer_"), f"Tool {tool.name!r} missing prefix"

    def test_tool_count(self, toolkit):
        tools = toolkit.get_tools()
        # 13 actions + 8 capture/recording + 4 loop = 25 minimum
        assert len(tools) >= 25, f"Expected >= 25 tools, got {len(tools)}"

    def test_expected_action_tools(self, toolkit):
        names = {t.name for t in toolkit.get_tools()}
        expected = {
            "computer_click_at",
            "computer_hover_at",
            "computer_type_text_at",
            "computer_scroll_document",
            "computer_scroll_at",
            "computer_wait",
            "computer_go_back",
            "computer_go_forward",
            "computer_search",
            "computer_navigate",
            "computer_key_combination",
            "computer_drag_and_drop",
            "computer_open_browser",
        }
        for name in expected:
            assert name in names, f"Tool {name!r} not found"

    def test_expected_capture_tools(self, toolkit):
        names = {t.name for t in toolkit.get_tools()}
        expected = {
            "computer_screenshot",
            "computer_screenshot_element",
            "computer_start_recording",
            "computer_stop_recording",
            "computer_start_tracing",
            "computer_stop_tracing",
            "computer_record_har",
            "computer_save_pdf",
        }
        for name in expected:
            assert name in names, f"Tool {name!r} not found"

    def test_expected_loop_tools(self, toolkit):
        names = {t.name for t in toolkit.get_tools()}
        expected = {
            "computer_define_task",
            "computer_run_task",
            "computer_run_loop",
            "computer_abort_loop",
        }
        for name in expected:
            assert name in names, f"Tool {name!r} not found"


class TestCoordinateDenormalization:
    """Tests for 0-1000 → pixel denormalization."""

    def test_denormalize_x_center(self, toolkit):
        assert toolkit._denormalize_x(500) == 640

    def test_denormalize_y_center(self, toolkit):
        assert toolkit._denormalize_y(500) == 360

    def test_denormalize_x_zero(self, toolkit):
        assert toolkit._denormalize_x(0) == 0

    def test_denormalize_x_max(self, toolkit):
        assert toolkit._denormalize_x(1000) == 1280

    def test_denormalize_y_zero(self, toolkit):
        assert toolkit._denormalize_y(0) == 0

    def test_denormalize_y_max(self, toolkit):
        assert toolkit._denormalize_y(1000) == 720


class TestActions:
    """Tests for action methods."""

    @pytest.mark.asyncio
    async def test_click_at_denormalization(self, toolkit):
        toolkit._backend.click_at.return_value = _env_state()
        result = await toolkit.click_at(x=500, y=500)
        toolkit._backend.click_at.assert_called_once_with(640, 360)
        assert result["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_hover_at_denormalization(self, toolkit):
        toolkit._backend.hover_at.return_value = _env_state()
        result = await toolkit.hover_at(x=250, y=250)
        toolkit._backend.hover_at.assert_called_once_with(320, 180)

    @pytest.mark.asyncio
    async def test_type_text_at(self, toolkit):
        toolkit._backend.type_text_at.return_value = _env_state()
        result = await toolkit.type_text_at(x=500, y=500, text="hello")
        toolkit._backend.type_text_at.assert_called_once_with(640, 360, "hello", press_enter=False, clear_before_typing=True)

    @pytest.mark.asyncio
    async def test_navigate(self, toolkit):
        toolkit._backend.navigate.return_value = _env_state("https://news.ycombinator.com")
        result = await toolkit.navigate(url="https://news.ycombinator.com")
        assert result["url"] == "https://news.ycombinator.com"

    @pytest.mark.asyncio
    async def test_key_combination_parsing(self, toolkit):
        toolkit._backend.key_combination.return_value = _env_state()
        await toolkit.key_combination(keys="control,c")
        toolkit._backend.key_combination.assert_called_once_with(["control", "c"])

    @pytest.mark.asyncio
    async def test_drag_and_drop_denormalization(self, toolkit):
        toolkit._backend.drag_and_drop.return_value = _env_state()
        await toolkit.drag_and_drop(x=0, y=0, destination_x=1000, destination_y=1000)
        toolkit._backend.drag_and_drop.assert_called_once_with(0, 0, 1280, 720)

    @pytest.mark.asyncio
    async def test_scroll_document(self, toolkit):
        toolkit._backend.scroll_document.return_value = _env_state()
        result = await toolkit.scroll_document("down")
        toolkit._backend.scroll_document.assert_called_once_with("down")

    @pytest.mark.asyncio
    async def test_go_back(self, toolkit):
        toolkit._backend.go_back.return_value = _env_state()
        result = await toolkit.go_back()
        assert result["screenshot_taken"] is True

    @pytest.mark.asyncio
    async def test_search(self, toolkit):
        toolkit._backend.search.return_value = _env_state("https://www.google.com")
        result = await toolkit.search()
        assert result["url"] == "https://www.google.com"


class TestCaptureTools:
    """Tests for screenshot and recording methods."""

    @pytest.mark.asyncio
    async def test_screenshot(self, toolkit):
        toolkit._backend.screenshot.return_value = b"\x89PNG"
        result = await toolkit.screenshot()
        assert result["screenshot_bytes"] == b"\x89PNG"

    @pytest.mark.asyncio
    async def test_screenshot_full_page(self, toolkit):
        toolkit._backend.screenshot.return_value = b"\x89PNG"
        await toolkit.screenshot(full_page=True)
        toolkit._backend.screenshot.assert_called_with(full_page=True)

    @pytest.mark.asyncio
    async def test_start_stop_recording(self, toolkit):
        toolkit._backend.start_recording = AsyncMock()
        toolkit._backend.stop_recording = AsyncMock(return_value="./recordings/video.webm")
        start_result = await toolkit.start_recording(output_dir="./recordings")
        assert start_result["status"] == "recording_started"
        stop_result = await toolkit.stop_recording()
        assert stop_result["video_path"] == "./recordings/video.webm"

    @pytest.mark.asyncio
    async def test_start_stop_tracing(self, toolkit):
        toolkit._backend.start_tracing = AsyncMock()
        toolkit._backend.stop_tracing = AsyncMock()
        await toolkit.start_tracing()
        result = await toolkit.stop_tracing(output_path="trace.zip")
        assert result["output_path"] == "trace.zip"

    @pytest.mark.asyncio
    async def test_save_pdf(self, toolkit):
        toolkit._backend.save_pdf = AsyncMock(return_value=b"%PDF")
        result = await toolkit.save_pdf(output_path="page.pdf")
        assert result["output_path"] == "page.pdf"


class TestTaskAndLoop:
    """Tests for define_task, run_task, run_loop, abort_loop."""

    @pytest.mark.asyncio
    async def test_define_task(self, toolkit):
        result = await toolkit.define_task(
            name="fill_form",
            description="Fill a registration form",
            steps=["Click name field", "Type name", "Submit"],
        )
        assert result["status"] == "task_defined"
        assert "fill_form" in toolkit._tasks
        assert toolkit._tasks["fill_form"].steps == ["Click name field", "Type name", "Submit"]

    @pytest.mark.asyncio
    async def test_run_task_undefined(self, toolkit):
        result = await toolkit.run_task(task="nonexistent")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_run_task_defined(self, toolkit):
        toolkit._backend.current_state = AsyncMock(return_value=_env_state())
        await toolkit.define_task(name="test", description="Test", steps=["Step 1"])
        result = await toolkit.run_task(task="test")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_run_loop_count(self, toolkit):
        toolkit._backend.current_state = AsyncMock(return_value=_env_state())
        await toolkit.define_task(name="loop_task", description="Loop", steps=["Step"])
        result = await toolkit.run_loop(task="loop_task", iterations=5)
        assert result["iterations_completed"] == 5
        assert result["stop_reason"] == "count"

    @pytest.mark.asyncio
    async def test_run_loop_max_cap(self, toolkit):
        toolkit._backend.current_state = AsyncMock(return_value=_env_state())
        await toolkit.define_task(name="loop_task2", description="Loop", steps=["Step"])
        # Ask for 200 iterations but cap at 10
        result = await toolkit.run_loop(task="loop_task2", iterations=200, max_iterations=10)
        assert result["iterations_completed"] <= 10
        assert result["stop_reason"] == "count"

    @pytest.mark.asyncio
    async def test_run_loop_max_reached(self, toolkit):
        toolkit._backend.current_state = AsyncMock(return_value=_env_state())
        await toolkit.define_task(name="inf_task", description="Infinite loop", steps=["Step"])
        result = await toolkit.run_loop(task="inf_task", max_iterations=3)
        assert result["iterations_completed"] == 3
        assert result["stop_reason"] == "max_reached"

    @pytest.mark.asyncio
    async def test_run_loop_params_list(self, toolkit):
        toolkit._backend.current_state = AsyncMock(return_value=_env_state())
        await toolkit.define_task(name="data_task", description="Data", steps=["Step"])
        result = await toolkit.run_loop(
            task="data_task",
            params_list=[{"q": "a"}, {"q": "b"}, {"q": "c"}],
        )
        assert result["iterations_completed"] == 3
        assert result["stop_reason"] == "count"

    @pytest.mark.asyncio
    async def test_abort_loop(self, toolkit):
        result = await toolkit.abort_loop()
        assert result["status"] == "loop_aborted"
        assert toolkit._loop_abort is True

    @pytest.mark.asyncio
    async def test_run_loop_aborted(self, toolkit):
        toolkit._backend.current_state = AsyncMock(return_value=_env_state())
        await toolkit.define_task(name="abortable", description="Abort", steps=["Step"])
        toolkit._loop_abort = True  # Pre-set abort flag
        result = await toolkit.run_loop(task="abortable", iterations=10)
        assert result["iterations_completed"] == 0
        assert result["stop_reason"] == "aborted"

    @pytest.mark.asyncio
    async def test_run_loop_undefined_task(self, toolkit):
        result = await toolkit.run_loop(task="missing_task")
        assert result["stop_reason"] == "error"
        assert "not defined" in result["error"]
