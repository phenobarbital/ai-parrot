"""Hierarchy + regression assertions for the FEAT-403 MCP reparenting
(TASK-2079).

No pre-existing server-side MCP test suite existed when TASK-2079
shipped (see its own completion note in
sdd/tasks/completed/TASK-2079-remote-base-shims.md) — these are the
three cheap hierarchy assertions its own Test Specification prescribed,
plus coverage for every remote transport and a regression guard for the
QuicMCPServer.handle_tools_call override removed on code-review
follow-up.
"""
import pytest
from parrot.mcp.config import MCPServerConfig
from parrot.mcp.local_server import LocalMCPServerBase
from parrot.mcp.server_base import MCPServerBase as CoreMCPServerBase
from parrot.mcp.transports.base import MCPServerBase, RemoteMCPServerBase
from parrot.mcp.transports.http import HttpMCPServer
from parrot.mcp.transports.sse import SseMCPServer
from parrot.mcp.transports.stdio import StdioMCPServer
from parrot.mcp.transports.unix import UnixMCPServer
from parrot.mcp.transports.websocket import WebSocketMCPServer
from parrot.tools.abstract import AbstractTool
from pydantic import BaseModel, Field

try:  # QUIC ships in the optional `ai-parrot-server[mcp]` extra (aioquic)
    from parrot.mcp.transports.quic import QuicMCPServer
except ImportError:  # pragma: no cover - exercised only without the extra
    QuicMCPServer = None


class EchoInput(BaseModel):
    text: str = Field(..., description="Text to echo")


class EchoTool(AbstractTool):
    """Echo input back"""
    name = "echo"
    description = "Echo input back"
    args_schema = EchoInput
    async def _execute(self, text: str) -> str:
        return text


class TestRemoteMCPServerBaseHierarchy:
    def test_remote_base_inherits_core(self):
        assert issubclass(RemoteMCPServerBase, CoreMCPServerBase)

    def test_backward_compat_alias(self):
        assert MCPServerBase is RemoteMCPServerBase


class TestStdioReparenting:
    def test_stdio_inherits_local(self):
        assert issubclass(StdioMCPServer, LocalMCPServerBase)


class TestRemoteTransportsReparenting:
    """All five remote transports must inherit RemoteMCPServerBase (core
    MCPServerBase's tool registration + JSON-RPC handlers), not just the
    server's old standalone MCPServerBase."""

    @pytest.mark.parametrize("transport_cls", [
        HttpMCPServer, SseMCPServer, UnixMCPServer,
        pytest.param(QuicMCPServer, marks=pytest.mark.requires_aioquic),
        WebSocketMCPServer,
    ])
    def test_transport_inherits_remote_base(self, transport_cls):
        assert issubclass(transport_cls, RemoteMCPServerBase)


@pytest.mark.requires_aioquic
class TestQuicHandleToolsCall:
    """Regression guard for the removed QuicMCPServer.handle_tools_call
    override, which called MCPToolAdapter.execute(**arguments) — broken
    against the adapter's real execute(self, arguments: dict) signature
    (any tool call would TypeError). QuicMCPServer now inherits the
    tested, correct handler from core via RemoteMCPServerBase.
    """

    def test_quic_does_not_override_handle_tools_call(self):
        assert "handle_tools_call" not in QuicMCPServer.__dict__

    @pytest.mark.asyncio
    async def test_quic_handle_tools_call_works(self):
        server = QuicMCPServer(MCPServerConfig(name="test-quic", transport="quic"))
        server.register_tool(EchoTool())
        result = await server.handle_tools_call(
            {"name": "echo", "arguments": {"text": "hi"}}
        )
        assert result["isError"] is False
        assert any("hi" in c["text"] for c in result["content"])
