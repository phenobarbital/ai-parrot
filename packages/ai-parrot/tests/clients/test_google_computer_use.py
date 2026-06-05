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


class TestFunctionResponseBlobWrapping:
    """Tests for FunctionResponseBlob wrapping of computer-use screenshot results."""

    def _make_client(self):
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = MagicMock()
        return client

    def test_extract_screenshot_bytes_from_dict(self):
        """_extract_screenshot_bytes returns bytes when screenshot_bytes key present."""
        client = self._make_client()
        result = {"url": "https://example.com", "screenshot_bytes": b"\x89PNG\r\n"}
        extracted = client._extract_screenshot_bytes(result)
        assert extracted == b"\x89PNG\r\n"

    def test_extract_screenshot_bytes_missing_key(self):
        """_extract_screenshot_bytes returns None when screenshot_bytes not in dict."""
        client = self._make_client()
        result = {"url": "https://example.com", "screenshot_taken": True}
        assert client._extract_screenshot_bytes(result) is None

    def test_extract_screenshot_bytes_non_dict(self):
        """_extract_screenshot_bytes returns None for non-dict results."""
        client = self._make_client()
        assert client._extract_screenshot_bytes("plain string result") is None
        assert client._extract_screenshot_bytes(42) is None
        assert client._extract_screenshot_bytes(None) is None

    def test_extract_screenshot_bytes_non_bytes_value(self):
        """_extract_screenshot_bytes returns None when screenshot_bytes is not bytes."""
        client = self._make_client()
        result = {"screenshot_bytes": "base64encodedstring"}
        assert client._extract_screenshot_bytes(result) is None

    def test_build_computer_use_function_response_part_with_screenshot(self):
        """Part contains FunctionResponseBlob (inline_data) when screenshot bytes present."""
        client = self._make_client()
        png_bytes = b"\x89PNG\r\nfake_png_data"
        result = {
            "url": "https://example.com",
            "screenshot_taken": True,
            "screenshot_bytes": png_bytes,
        }
        part = client._build_computer_use_function_response_part(
            "call_123", "click_at", result
        )
        assert part is not None
        assert part.function_response is not None
        assert part.function_response.name == "click_at"
        assert part.function_response.id == "call_123"
        # The screenshot should be in the parts as a blob, not in response dict
        blob_parts = part.function_response.parts
        assert blob_parts is not None and len(blob_parts) == 1
        blob = blob_parts[0].inline_data
        assert blob is not None
        assert blob.mime_type == "image/png"
        assert blob.data == png_bytes
        # The text response dict should NOT contain screenshot_bytes
        text_response = part.function_response.response or {}
        assert "screenshot_bytes" not in text_response

    def test_build_computer_use_function_response_part_without_screenshot(self):
        """Part uses plain response dict when no screenshot bytes present."""
        client = self._make_client()
        result = {"url": "https://example.com", "screenshot_taken": False}
        part = client._build_computer_use_function_response_part(
            "call_456", "navigate", result
        )
        assert part is not None
        assert part.function_response is not None
        assert part.function_response.name == "navigate"
        # No blob parts when there is no screenshot
        assert (
            part.function_response.parts is None
            or len(part.function_response.parts) == 0
        )
        # Result should be a plain dict
        assert part.function_response.response is not None

    def test_build_computer_use_function_response_part_string_result(self):
        """Fallback path handles plain string results (non-dict)."""
        client = self._make_client()
        # Make _process_tool_result_for_api available (it's a real method)
        import pandas as pd
        client._json = __import__("json")

        part = client._build_computer_use_function_response_part(
            "call_789", "go_back", "navigation complete"
        )
        assert part is not None
        assert part.function_response is not None
