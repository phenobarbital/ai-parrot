"""Unit tests for parrot_tools.computer.agent (TASK-1478)."""
from unittest.mock import MagicMock, patch

import pytest

from parrot_tools.computer.agent import ComputerAgent


class TestComputerAgentTools:
    """Tests for agent_tools() composition."""

    def test_agent_tools_without_scraping(self):
        """agent_tools() returns ComputerInteractionToolkit tools only."""
        agent = ComputerAgent.__new__(ComputerAgent)
        agent._computer_toolkit = MagicMock()
        agent._computer_toolkit.get_tools.return_value = [MagicMock()] * 25
        agent._include_scraping = False
        agent._scraping_toolkit = None
        tools = agent.agent_tools()
        assert len(tools) == 25

    def test_agent_tools_with_scraping_toolkit_included(self):
        """agent_tools() includes scraping tools when _scraping_toolkit is set."""
        agent = ComputerAgent.__new__(ComputerAgent)
        agent._computer_toolkit = MagicMock()
        agent._computer_toolkit.get_tools.return_value = [MagicMock()] * 25
        agent._include_scraping = True

        # Mock the cached scraping toolkit with 5 additional tools
        mock_scraping = MagicMock()
        mock_scraping.get_tools.return_value = [MagicMock()] * 5
        agent._scraping_toolkit = mock_scraping

        tools = agent.agent_tools()
        # Should have 25 computer tools + 5 scraping tools
        assert len(tools) == 30
        mock_scraping.get_tools.assert_called_once()

    def test_agent_tools_include_scraping_flag(self):
        """include_scraping flag is stored on the agent."""
        agent = ComputerAgent.__new__(ComputerAgent)
        agent._computer_toolkit = MagicMock()
        agent._computer_toolkit.get_tools.return_value = []
        agent._include_scraping = True
        agent._scraping_toolkit = None
        assert agent._include_scraping is True

    def test_agent_tools_scraping_exception_handled(self):
        """When _scraping_toolkit is None (init failed), agent_tools() returns only computer tools."""
        agent = ComputerAgent.__new__(ComputerAgent)
        computer_tools = [MagicMock()] * 25
        agent._computer_toolkit = MagicMock()
        agent._computer_toolkit.get_tools.return_value = computer_tools
        agent._include_scraping = True
        # Simulate that init-time WebScrapingToolkit creation failed
        agent._scraping_toolkit = None

        tools = agent.agent_tools()
        # Should fall back to computer tools only
        assert len(tools) == 25


class TestComputerAgentSafetyMode:
    """Tests for safety mode configuration."""

    def test_safety_mode_default(self):
        agent = ComputerAgent.__new__(ComputerAgent)
        agent._safety_mode = "auto"
        assert agent._safety_mode == "auto"

    def test_handle_safety_auto_returns_true(self):
        agent = ComputerAgent.__new__(ComputerAgent)
        agent._safety_mode = "auto"
        result = agent.handle_safety_decision({"action": "click", "warning": "phishing"})
        assert result is True

    def test_handle_safety_interactive_emits_event(self):
        agent = ComputerAgent.__new__(ComputerAgent)
        agent._safety_mode = "interactive"
        agent._safety_callback = None  # No callback — defaults to True
        agent.emit = MagicMock()
        decision = {"action": "fill", "warning": "sensitive_data"}
        result = agent.handle_safety_decision(decision)
        agent.emit.assert_called_once_with("safety_decision", decision)
        assert result is True  # Default proceeds even in interactive mode (no callback)


class TestComputerAgentScreenshotPruning:
    """Tests for screenshot memory pruning."""

    def _make_agent(self, max_turns=3):
        agent = ComputerAgent.__new__(ComputerAgent)
        agent._max_screenshot_turns = max_turns
        return agent

    def test_prune_empty_history(self):
        agent = self._make_agent()
        assert agent.prune_screenshots([]) == []

    def test_prune_no_screenshots(self):
        agent = self._make_agent()
        history = [{"role": "user", "content": "hello"}] * 5
        result = agent.prune_screenshots(history)
        assert len(result) == 5

    def test_prune_within_limit(self):
        agent = self._make_agent(max_turns=3)
        history = [
            {"role": "tool", "images": [b"\x89PNG"]},
            {"role": "tool", "images": [b"\x89PNG"]},
            {"role": "tool", "images": [b"\x89PNG"]},
        ]
        result = agent.prune_screenshots(history)
        # All 3 turns within limit — screenshots preserved
        assert all("images" in t for t in result)

    def test_prune_beyond_limit(self):
        agent = self._make_agent(max_turns=2)
        history = [
            {"role": "tool", "images": [b"\x89PNG_1"]},
            {"role": "tool", "images": [b"\x89PNG_2"]},
            {"role": "tool", "images": [b"\x89PNG_3"]},
        ]
        result = agent.prune_screenshots(history)
        # 3 screenshot turns; only last 2 retain images
        screenshot_count = sum(1 for t in result if "images" in t)
        assert screenshot_count == 2

    def test_has_screenshot_false_for_plain_turn(self):
        agent = self._make_agent()
        assert agent._has_screenshot({"role": "user", "content": "text"}) is False

    def test_has_screenshot_true_for_images(self):
        agent = self._make_agent()
        assert agent._has_screenshot({"images": [b"\x89PNG"]}) is True

    def test_strip_screenshots_removes_images(self):
        agent = self._make_agent()
        turn = {"role": "tool", "content": "result", "images": [b"\x89PNG"]}
        stripped = agent._strip_screenshots(turn)
        assert "images" not in stripped
        assert stripped["content"] == "result"
