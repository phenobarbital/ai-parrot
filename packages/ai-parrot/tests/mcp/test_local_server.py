import pytest
from pydantic import BaseModel, Field

from parrot.tools.abstract import AbstractTool
from parrot.mcp.local_server import StdioMCPServer, LocalMCPServerBase
from parrot.mcp.server_base import LocalServerConfig


class EchoInput(BaseModel):
    text: str = Field(..., description="Text to echo")


class EchoTool(AbstractTool):
    """Echo input back"""
    name = "echo"
    description = "Echo input back"
    args_schema = EchoInput
    async def _execute(self, text: str) -> str:
        return text


class TestLocalMCPServerBase:
    def test_is_mcp_server_base_subclass(self):
        assert issubclass(StdioMCPServer, LocalMCPServerBase)


class TestStdioMCPServer:
    @pytest.mark.asyncio
    async def test_handle_request_initialize(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        response = await server._handle_request({
            "jsonrpc": "2.0", "id": 1,
            "method": "initialize", "params": {}
        })
        assert response["id"] == 1
        assert response["result"]["protocolVersion"] == "2024-11-05"

    @pytest.mark.asyncio
    async def test_handle_request_tools_list(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        # register a tool first
        server.register_tool(EchoTool())
        response = await server._handle_request({
            "jsonrpc": "2.0", "id": 2,
            "method": "tools/list", "params": {}
        })
        assert len(response["result"]["tools"]) == 1

    @pytest.mark.asyncio
    async def test_handle_request_tools_call(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        server.register_tool(EchoTool())
        response = await server._handle_request({
            "jsonrpc": "2.0", "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"text": "hi"}}
        })
        assert response["result"]["isError"] is False

    @pytest.mark.asyncio
    async def test_handle_notification_no_response(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        response = await server._handle_request({
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        })
        assert response is None

    @pytest.mark.asyncio
    async def test_handle_unknown_method(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        response = await server._handle_request({
            "jsonrpc": "2.0", "id": 4,
            "method": "unknown/method", "params": {}
        })
        assert "error" in response
        assert response["error"]["code"] == -32603

    @pytest.mark.asyncio
    async def test_stop_clears_running_flag(self):
        server = StdioMCPServer(LocalServerConfig(name="test"))
        server._running = True
        await server.stop()
        assert server._running is False
