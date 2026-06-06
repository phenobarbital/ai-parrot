"""Integration tests for the computer-use agent feature (TASK-1482).

Tests the full chain:
  ComputerInteractionToolkit -> AsyncComputerBackend
  ComputerAgent composition and screenshot pruning
  GoogleGenAIClient tool building with ComputerUse

All tests use mocked Playwright and mocked LLM responses — no live
browser or network calls are made.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot_tools.computer.toolkit import ComputerInteractionToolkit
from parrot_tools.computer.models import EnvState


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_backend_mock(url: str = "https://example.com") -> MagicMock:
    """Return a MagicMock that mimics AsyncComputerBackend.

    All async action methods return an EnvState; ``screen_size`` is sync.
    """
    backend = AsyncMock()
    backend.screen_size = MagicMock(return_value=(1280, 720))
    _state = EnvState(screenshot=b"png", url=url)
    backend.navigate.return_value = _state
    backend.click_at.return_value = EnvState(screenshot=b"png2", url=f"{url}/page")
    backend.current_state.return_value = _state
    backend.type_text_at.return_value = _state
    backend.screenshot.return_value = _state
    return backend


# ---------------------------------------------------------------------------
# Test 1: navigate + click flow
# ---------------------------------------------------------------------------


class TestNavigateAndClickFlow:
    """Toolkit dispatches navigate/click calls to backend and returns state."""

    @pytest.mark.asyncio
    async def test_navigate_returns_url(self):
        """navigate() returns a dict with the correct url."""
        toolkit = ComputerInteractionToolkit(viewport=(1280, 720))
        toolkit._backend = _make_backend_mock("https://example.com")
        toolkit._started = True

        result = await toolkit.navigate(url="https://example.com")

        assert isinstance(result, dict)
        assert result["url"] == "https://example.com"
        toolkit._backend.navigate.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_click_returns_new_url(self):
        """click_at() denormalises coordinates and returns updated state."""
        toolkit = ComputerInteractionToolkit(viewport=(1280, 720))
        toolkit._backend = _make_backend_mock("https://example.com")
        toolkit._started = True

        result = await toolkit.click_at(x=500, y=300)

        assert isinstance(result, dict)
        assert "url" in result
        # Backend click_at is called with pixel coords (denormalized)
        toolkit._backend.click_at.assert_called_once()
        call_args = toolkit._backend.click_at.call_args
        # x=500 -> int(500/1000*1280) = 640; y=300 -> int(300/1000*720) = 216
        assert call_args.kwargs.get("x", call_args.args[0] if call_args.args else None) == 640
        assert call_args.kwargs.get("y", call_args.args[1] if len(call_args.args) > 1 else None) == 216

    @pytest.mark.asyncio
    async def test_navigate_then_click_sequence(self):
        """Sequential navigate + click both succeed and return expected data."""
        toolkit = ComputerInteractionToolkit(viewport=(1280, 720))
        toolkit._backend = _make_backend_mock("https://example.com")
        toolkit._started = True

        nav_result = await toolkit.navigate(url="https://example.com")
        assert nav_result["url"] == "https://example.com"

        click_result = await toolkit.click_at(x=500, y=300)
        assert "url" in click_result

    @pytest.mark.asyncio
    async def test_screenshot_included_in_navigate_result(self):
        """navigate() result includes screenshot bytes in base64 field."""
        toolkit = ComputerInteractionToolkit(viewport=(1280, 720))
        toolkit._backend = _make_backend_mock("https://example.com")
        toolkit._started = True

        result = await toolkit.navigate(url="https://example.com")

        assert "screenshot_bytes" in result


# ---------------------------------------------------------------------------
# Test 2: loop pagination with count-based stop
# ---------------------------------------------------------------------------


class TestLoopPagination:
    """run_loop() iterates correctly and stops with the expected reason."""

    @pytest.mark.asyncio
    async def test_count_based_loop_runs_n_iterations(self):
        """Loop with iterations=5 runs exactly 5 times and stops with 'count'."""
        toolkit = ComputerInteractionToolkit(viewport=(1280, 720))
        toolkit._backend = _make_backend_mock("https://example.com")
        toolkit._started = True

        await toolkit.define_task(
            name="next_page",
            description="Click the Next button",
            steps=["Click the Next button on the page"],
        )
        result = await toolkit.run_loop(
            task="next_page", iterations=5, collect_results=True
        )

        assert result["iterations_completed"] == 5
        assert result["stop_reason"] == "count"
        assert len(result["results"]) == 5

    @pytest.mark.asyncio
    async def test_loop_respects_max_iterations_cap(self):
        """max_iterations=3 caps a loop requesting iterations=10."""
        toolkit = ComputerInteractionToolkit(viewport=(1280, 720))
        toolkit._backend = _make_backend_mock("https://example.com")
        toolkit._started = True

        await toolkit.define_task(
            name="page_task",
            description="Paginate through results",
            steps=["Go to the next page"],
        )
        result = await toolkit.run_loop(
            task="page_task", iterations=10, max_iterations=3, collect_results=True
        )

        assert result["iterations_completed"] == 3
        assert result["stop_reason"] == "count"

    @pytest.mark.asyncio
    async def test_loop_aborts_when_abort_loop_called(self):
        """abort_loop() sets flag and subsequent iterations are skipped."""
        toolkit = ComputerInteractionToolkit(viewport=(1280, 720))
        toolkit._backend = _make_backend_mock("https://example.com")
        toolkit._started = True

        await toolkit.define_task(
            name="abortable",
            description="Task that can be aborted",
            steps=["Perform an action"],
        )
        # Pre-set the abort flag (simulates concurrent abort_loop() call)
        toolkit._loop_abort = True
        result = await toolkit.run_loop(
            task="abortable", iterations=10, collect_results=True
        )

        assert result["stop_reason"] == "aborted"
        assert result["iterations_completed"] == 0

    @pytest.mark.asyncio
    async def test_loop_unknown_task_returns_error(self):
        """run_loop() for an undefined task returns a well-formed error dict."""
        toolkit = ComputerInteractionToolkit(viewport=(1280, 720))
        toolkit._backend = _make_backend_mock("https://example.com")
        toolkit._started = True

        result = await toolkit.run_loop(task="nonexistent", iterations=3)

        assert result["stop_reason"] == "error"
        assert result["iterations_completed"] == 0


# ---------------------------------------------------------------------------
# Test 3: hybrid agent with ComputerInteraction + optional WebScraping
# ---------------------------------------------------------------------------


class TestHybridAgentToolComposition:
    """ComputerAgent composes tools correctly with and without scraping."""

    def test_computer_agent_tools_without_scraping(self):
        """agent_tools() returns only ComputerInteractionToolkit tools by default."""
        from parrot_tools.computer.agent import ComputerAgent
        from parrot.bots.agent import Agent

        # Instantiate without Agent.__init__ to avoid LLM client setup
        agent = ComputerAgent.__new__(ComputerAgent)
        agent._computer_toolkit = ComputerInteractionToolkit(viewport=(1280, 720))
        agent._include_scraping = False
        agent._safety_mode = "auto"
        agent._max_screenshot_turns = 3

        tools = agent.agent_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0
        # All returned tools have a callable 'func' or are AbstractTool instances
        for tool in tools:
            assert hasattr(tool, "name"), f"Tool {tool!r} has no 'name' attribute"

    def test_computer_agent_tools_with_scraping_fails_gracefully(self):
        """When WebScrapingToolkit import fails, agent_tools() still returns computer tools."""
        from parrot_tools.computer.agent import ComputerAgent

        agent = ComputerAgent.__new__(ComputerAgent)
        agent._computer_toolkit = ComputerInteractionToolkit(viewport=(1280, 720))
        agent._include_scraping = True
        agent._safety_mode = "auto"
        agent._max_screenshot_turns = 3
        # Simulate failed toolkit init (as happens when import fails at __init__ time)
        agent._scraping_toolkit = None

        tools = agent.agent_tools()
        # Should still return computer tools without raising
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_computer_agent_prune_screenshots_keeps_recent(self):
        """prune_screenshots keeps the last max_screenshot_turns screenshot turns."""
        from parrot_tools.computer.agent import ComputerAgent

        agent = ComputerAgent.__new__(ComputerAgent)
        agent._computer_toolkit = ComputerInteractionToolkit(viewport=(1280, 720))
        agent._include_scraping = False
        agent._safety_mode = "auto"
        agent._max_screenshot_turns = 2

        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "ok", "images": [b"png1"]},
            {"role": "assistant", "content": "step2", "images": [b"png2"]},
            {"role": "assistant", "content": "step3", "images": [b"png3"]},
        ]
        pruned = agent.prune_screenshots(history)

        # The first screenshot turn (oldest) should be stripped
        assert "images" not in pruned[1] or not pruned[1].get("images")
        # The last two turns with screenshots should still have images
        assert pruned[2].get("images")
        assert pruned[3].get("images")

    def test_computer_agent_safety_mode_auto_returns_true(self):
        """handle_safety_decision() in auto mode logs and returns True."""
        from parrot_tools.computer.agent import ComputerAgent

        agent = ComputerAgent.__new__(ComputerAgent)
        agent._computer_toolkit = ComputerInteractionToolkit(viewport=(1280, 720))
        agent._include_scraping = False
        agent._safety_mode = "auto"
        agent._max_screenshot_turns = 3

        result = agent.handle_safety_decision({"type": "dangerous_url"})
        assert result is True


# ---------------------------------------------------------------------------
# Test 4: GoogleGenAIClient builds tools with ComputerUse
# ---------------------------------------------------------------------------


class TestGoogleClientComputerUseIntegration:
    """GoogleGenAIClient correctly wires up ComputerUse tool config."""

    def test_build_tools_computer_use_returns_one_tool(self):
        """_build_tools('computer_use') returns a single Tool with computer_use set."""
        from parrot.clients.google.client import GoogleGenAIClient

        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = MagicMock()
        # Attach a minimal config object (no parrot_tools.computer dependency needed)
        class _Config:
            excluded_actions: list = []
        client._computer_use_config = _Config()

        tools = client._build_tools("computer_use")

        assert tools is not None
        assert len(tools) == 1
        assert tools[0].computer_use is not None

    def test_build_tools_computer_use_no_config_still_works(self):
        """Without _computer_use_config, _build_tools still returns a valid tool."""
        from parrot.clients.google.client import GoogleGenAIClient

        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = MagicMock()
        # No _computer_use_config attribute set at all

        tools = client._build_tools("computer_use")
        assert tools is not None
        assert len(tools) == 1

    def test_build_tools_computer_use_with_excluded_actions(self):
        """excluded_actions are forwarded to ComputerUse."""
        from parrot.clients.google.client import GoogleGenAIClient

        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = MagicMock()

        class _Config:
            excluded_actions = ["drag_and_drop", "scroll"]
        client._computer_use_config = _Config()

        tools = client._build_tools("computer_use")
        assert tools[0].computer_use.excluded_predefined_functions == [
            "drag_and_drop",
            "scroll",
        ]

    def test_build_tools_custom_functions_not_affected(self):
        """computer_use branch does not break existing custom_functions path."""
        from parrot.clients.google.client import GoogleGenAIClient

        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = MagicMock()
        client._request_tools = {}
        mock_manager = MagicMock()
        mock_manager.all_tools.return_value = []
        client.tool_manager = mock_manager

        result = client._build_tools("custom_functions")
        # Should return list (possibly empty) without raising
        assert result is None or isinstance(result, list)

    def test_is_computer_use_model_detects_correct_prefix(self):
        """_is_computer_use_model identifies computer-use models correctly."""
        from parrot.clients.google.client import GoogleGenAIClient

        assert GoogleGenAIClient._is_computer_use_model(
            "gemini-2.5-computer-use-preview-10-2025"
        ) is True
        assert GoogleGenAIClient._is_computer_use_model("gemini-3-flash-preview") is True
        assert GoogleGenAIClient._is_computer_use_model("gemini-2.5-pro") is False
        assert GoogleGenAIClient._is_computer_use_model("gemini-2.5-flash") is False

    def test_requires_thinking_for_computer_use_model(self):
        """_requires_thinking returns True for computer-use models."""
        from parrot.clients.google.client import GoogleGenAIClient

        assert GoogleGenAIClient._requires_thinking(
            "gemini-2.5-computer-use-preview-10-2025"
        ) is True
