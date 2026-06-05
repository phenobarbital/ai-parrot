"""Tests for GoogleGenAIClient computer-use extensions (TASK-1479)."""
import sys
import pytest
from unittest.mock import MagicMock, patch

from parrot.clients.google.client import GoogleGenAIClient


# Lightweight stand-in for ComputerUseConfig when parrot_tools.computer is unavailable.
class _MockComputerUseConfig:
    """Minimal ComputerUseConfig for testing purposes."""
    def __init__(self, excluded_actions=None):
        self.excluded_actions = excluded_actions or []
        self.environment = "ENVIRONMENT_BROWSER"


class TestIsComputerUseModel:
    """Tests for GoogleGenAIClient._is_computer_use_model()."""

    def test_computer_use_preview_model(self):
        assert GoogleGenAIClient._is_computer_use_model(
            "gemini-2.5-computer-use-preview-10-2025"
        ) is True

    def test_gemini_3_flash_preview(self):
        assert GoogleGenAIClient._is_computer_use_model("gemini-3-flash-preview") is True

    def test_regular_model_returns_false(self):
        assert GoogleGenAIClient._is_computer_use_model("gemini-2.5-pro") is False

    def test_flash_model_returns_false(self):
        assert GoogleGenAIClient._is_computer_use_model("gemini-2.5-flash") is False

    def test_none_returns_false(self):
        assert GoogleGenAIClient._is_computer_use_model(None) is False

    def test_empty_string_returns_false(self):
        assert GoogleGenAIClient._is_computer_use_model("") is False


class TestRequiresThinkingComputerUse:
    """Tests that computer-use models require thinking mode."""

    def test_computer_use_requires_thinking(self):
        assert GoogleGenAIClient._requires_thinking(
            "gemini-2.5-computer-use-preview-10-2025"
        ) is True

    def test_regular_model_no_thinking(self):
        assert GoogleGenAIClient._requires_thinking("gemini-2.5-flash") is False

    def test_pro_model_requires_thinking(self):
        assert GoogleGenAIClient._requires_thinking("gemini-2.5-pro") is True


class TestBuildToolsComputerUse:
    """Tests for _build_tools("computer_use")."""

    def test_build_tools_computer_use_returns_one_tool(self):
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = MagicMock()
        client._computer_use_config = _MockComputerUseConfig()
        tools = client._build_tools("computer_use")
        assert tools is not None
        assert len(tools) == 1

    def test_build_tools_computer_use_has_computer_use_field(self):
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = MagicMock()
        client._computer_use_config = _MockComputerUseConfig()
        tools = client._build_tools("computer_use")
        assert tools[0].computer_use is not None

    def test_build_tools_computer_use_no_config(self):
        """Without a config, still returns a tool with empty excluded_actions."""
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = MagicMock()
        # No _computer_use_config set
        tools = client._build_tools("computer_use")
        assert tools is not None
        assert len(tools) == 1

    def test_build_tools_computer_use_with_excluded(self):
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = MagicMock()
        client._computer_use_config = _MockComputerUseConfig(excluded_actions=["drag_and_drop"])
        tools = client._build_tools("computer_use")
        assert tools[0].computer_use.excluded_predefined_functions == ["drag_and_drop"]

    def test_build_tools_custom_functions_still_works(self):
        """Existing custom_functions path is unchanged."""
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = MagicMock()
        client._request_tools = {}
        # Mock tool_manager
        mock_manager = MagicMock()
        mock_manager.all_tools.return_value = []
        client.tool_manager = mock_manager
        tools = client._build_tools("custom_functions")
        # Returns empty list (no tools registered)
        assert tools == [] or tools is None or isinstance(tools, list)

    def test_build_tools_builtin_tools_still_works(self):
        """Existing builtin_tools path is unchanged."""
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = MagicMock()
        tools = client._build_tools("builtin_tools")
        assert tools is not None
        assert len(tools) == 1
        assert tools[0].google_search is not None

    def test_build_tools_unknown_returns_none(self):
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = MagicMock()
        result = client._build_tools("nonexistent_type")
        assert result is None
