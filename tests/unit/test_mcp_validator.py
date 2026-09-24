"""Unit tests for validate_mcp_http and MCPValidationError (TASK-1038).

The production integration module is imported normally, then MCPClient is
patched at the module level so no real network calls are made. Keeping test
doubles out of ``sys.modules`` prevents this module's collection from
poisoning later MCP imports.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.mcp import integration as _INTEGRATION_MOD
from parrot.mcp.integration import MCPValidationError, validate_mcp_http

# Helpers


def _make_config(url: str = "http://mcp.example.com") -> MagicMock:
    """Return a minimal MCPServerConfig mock."""
    cfg = MagicMock()
    cfg.url = url
    return cfg


def _patch_mcp_client(client_mock: MagicMock):
    """Context manager: patch MCPClient on the live integration module."""
    return patch.object(_INTEGRATION_MOD, "MCPClient", return_value=client_mock)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestValidateMCPHTTP:
    """Tests for validate_mcp_http."""

    @pytest.mark.asyncio
    async def test_success_calls_connect_and_list_tools(self) -> None:
        """On a healthy server: connect, list_tools and disconnect are each called once."""
        config = _make_config()
        client_mock = MagicMock()
        client_mock.connect = AsyncMock()
        client_mock.get_available_tools = AsyncMock(return_value=[{"name": "tool1"}])
        client_mock.disconnect = AsyncMock()

        with _patch_mcp_client(client_mock):
            await validate_mcp_http(config)

        client_mock.connect.assert_called_once()
        client_mock.get_available_tools.assert_called_once()
        client_mock.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_no_exception_on_empty_tool_list(self) -> None:
        """An empty tool list is still a valid list — no exception raised."""
        config = _make_config()
        client_mock = MagicMock()
        client_mock.connect = AsyncMock()
        client_mock.get_available_tools = AsyncMock(return_value=[])
        client_mock.disconnect = AsyncMock()

        with _patch_mcp_client(client_mock):
            await validate_mcp_http(config)  # must not raise

    @pytest.mark.asyncio
    async def test_connection_refused_raises_validation_error(self) -> None:
        """ConnectionRefusedError is converted to MCPValidationError."""
        config = _make_config()
        client_mock = MagicMock()
        client_mock.connect = AsyncMock(side_effect=ConnectionRefusedError("refused"))
        client_mock.disconnect = AsyncMock()

        with _patch_mcp_client(client_mock):
            with pytest.raises(MCPValidationError, match="handshake failed"):
                await validate_mcp_http(config)

    @pytest.mark.asyncio
    async def test_timeout_raises_validation_error(self) -> None:
        """TimeoutError on connect is wrapped in MCPValidationError."""
        config = _make_config()
        client_mock = MagicMock()
        client_mock.connect = AsyncMock(side_effect=TimeoutError("timed out"))
        client_mock.disconnect = AsyncMock()

        with _patch_mcp_client(client_mock):
            with pytest.raises(MCPValidationError):
                await validate_mcp_http(config)

    @pytest.mark.asyncio
    async def test_disconnect_always_called_even_on_connect_error(self) -> None:
        """disconnect() is called in the finally block even if connect() fails."""
        config = _make_config()
        client_mock = MagicMock()
        client_mock.connect = AsyncMock(side_effect=RuntimeError("boom"))
        client_mock.disconnect = AsyncMock()

        with _patch_mcp_client(client_mock):
            with pytest.raises(MCPValidationError):
                await validate_mcp_http(config)

        client_mock.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_always_called_even_on_tool_list_error(self) -> None:
        """disconnect() is called even when get_available_tools raises."""
        config = _make_config()
        client_mock = MagicMock()
        client_mock.connect = AsyncMock()
        client_mock.get_available_tools = AsyncMock(side_effect=RuntimeError("tools boom"))
        client_mock.disconnect = AsyncMock()

        with _patch_mcp_client(client_mock):
            with pytest.raises(MCPValidationError, match="handshake failed"):
                await validate_mcp_http(config)

        client_mock.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_error_is_suppressed(self) -> None:
        """If disconnect raises, the original error is not masked."""
        config = _make_config()
        client_mock = MagicMock()
        client_mock.connect = AsyncMock(side_effect=ConnectionRefusedError("refused"))
        client_mock.disconnect = AsyncMock(side_effect=RuntimeError("disconnect also failed"))

        with _patch_mcp_client(client_mock):
            with pytest.raises(MCPValidationError, match="handshake failed"):
                await validate_mcp_http(config)
        # No RuntimeError from disconnect escaped

    @pytest.mark.asyncio
    async def test_unexpected_tool_response_raises_validation_error(self) -> None:
        """If get_available_tools returns non-list, MCPValidationError is raised."""
        config = _make_config()
        client_mock = MagicMock()
        client_mock.connect = AsyncMock()
        client_mock.get_available_tools = AsyncMock(return_value={"not": "a list"})
        client_mock.disconnect = AsyncMock()

        with _patch_mcp_client(client_mock):
            with pytest.raises(MCPValidationError, match="unexpected tool listing"):
                await validate_mcp_http(config)

    @pytest.mark.asyncio
    async def test_error_message_contains_server_url(self) -> None:
        """The MCPValidationError message includes the server URL."""
        url = "http://mcp.test:8080"
        config = _make_config(url=url)
        client_mock = MagicMock()
        client_mock.connect = AsyncMock(side_effect=ConnectionRefusedError("no conn"))
        client_mock.disconnect = AsyncMock()

        with _patch_mcp_client(client_mock):
            with pytest.raises(MCPValidationError, match=url):
                await validate_mcp_http(config)


class TestMCPValidationError:
    """Tests for the MCPValidationError exception class."""

    def test_is_exception_subclass(self) -> None:
        """MCPValidationError must be a subclass of Exception."""
        assert issubclass(MCPValidationError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        """MCPValidationError can be raised and caught by its own type."""
        with pytest.raises(MCPValidationError, match="test msg"):
            raise MCPValidationError("test msg")

    def test_importable_from_integration(self) -> None:
        """Both symbols must be defined by the loaded integration module."""
        assert issubclass(_INTEGRATION_MOD.MCPValidationError, Exception)
        import asyncio

        assert asyncio.iscoroutinefunction(_INTEGRATION_MOD.validate_mcp_http)
