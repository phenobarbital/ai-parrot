"""Unit tests for validate_mcp_http and MCPValidationError (TASK-1038).

We load validate_mcp_http and MCPValidationError directly from the source
file, bypassing the heavy parrot package chain (navconfig, Cython modules,
etc.), then patch MCPClient at the module level so no real network calls
are made.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub out heavy dependencies before loading the module.
# ---------------------------------------------------------------------------

_STUBS: list[str] = [
    "navconfig",
    "navconfig.config",
    "parrot.mcp.context",
    "parrot.mcp.oauth",
    "parrot.mcp.client",
    "parrot.mcp.transports",
    "parrot.mcp.transports.stdio",
    "parrot.mcp.transports.unix",
    "parrot.mcp.transports.http",
    "parrot.mcp.transports.websocket",
    "parrot.mcp.transports.sse",
    "parrot.mcp.transports.quic",
    "parrot.mcp.chrome",
    "parrot.mcp.filtering",
    "parrot.tools.abstract",
]

for _stub_name in _STUBS:
    if _stub_name not in sys.modules:
        _mod = types.ModuleType(_stub_name)
        # Provide common attributes that integration.py references at import time.
        _mod.BASE_DIR = Path("/tmp")  # type: ignore[attr-defined]
        _mod.config = MagicMock()  # type: ignore[attr-defined]
        _mod.ReadonlyContext = MagicMock()  # type: ignore[attr-defined]
        _mod.AbstractTool = MagicMock()  # type: ignore[attr-defined]
        _mod.ToolResult = MagicMock()  # type: ignore[attr-defined]
        _mod.OAuthManager = MagicMock()  # type: ignore[attr-defined]
        _mod.InMemoryTokenStore = MagicMock()  # type: ignore[attr-defined]
        _mod.RedisTokenStore = MagicMock()  # type: ignore[attr-defined]
        _mod.TokenStore = MagicMock()  # type: ignore[attr-defined]
        _mod.VaultTokenStore = MagicMock()  # type: ignore[attr-defined]
        _mod.MCPClientConfig = MagicMock()  # type: ignore[attr-defined]
        _mod.MCPConnectionError = Exception  # type: ignore[attr-defined]
        _mod.StdioMCPSession = MagicMock()  # type: ignore[attr-defined]
        _mod.UnixMCPSession = MagicMock()  # type: ignore[attr-defined]
        _mod.HttpMCPSession = MagicMock()  # type: ignore[attr-defined]
        _mod.WebSocketMCPSession = MagicMock()  # type: ignore[attr-defined]
        _mod.SseMCPSession = MagicMock()  # type: ignore[attr-defined]
        _mod.QuicMCPSession = MagicMock()  # type: ignore[attr-defined]
        _mod.QuicMCPConfig = MagicMock()  # type: ignore[attr-defined]
        _mod.SerializationFormat = MagicMock()  # type: ignore[attr-defined]
        _mod.ChromeManager = MagicMock()  # type: ignore[attr-defined]
        _mod.ToolPredicate = MagicMock()  # type: ignore[attr-defined]
        _mod.filter_tools = MagicMock()  # type: ignore[attr-defined]
        sys.modules[_stub_name] = _mod

_WT_ROOT = Path(__file__).resolve().parents[2]
_INTEGRATION_SRC = (
    _WT_ROOT / "packages" / "ai-parrot" / "src" / "parrot" / "mcp" / "integration.py"
)

_MOD_NAME = "parrot.mcp.integration"
if _MOD_NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_MOD_NAME, str(_INTEGRATION_SRC))
    _imod = importlib.util.module_from_spec(_spec)
    sys.modules[_MOD_NAME] = _imod
    try:
        _spec.loader.exec_module(_imod)
    except Exception:
        pass  # Partial load is OK — we only need the tail functions

from parrot.mcp.integration import MCPValidationError, validate_mcp_http  # noqa: E402

# Grab the live module object so we can patch.object on it directly
# (patch("parrot.mcp.integration.X") fails because parrot.mcp is not a
#  real sub-package in this test environment — we loaded it via importlib).
_INTEGRATION_MOD = sys.modules["parrot.mcp.integration"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        """Both symbols must be importable from parrot.mcp.integration."""
        from parrot.mcp.integration import MCPValidationError as MVE
        from parrot.mcp.integration import validate_mcp_http as vmh

        assert issubclass(MVE, Exception)
        import asyncio
        assert asyncio.iscoroutinefunction(vmh)
