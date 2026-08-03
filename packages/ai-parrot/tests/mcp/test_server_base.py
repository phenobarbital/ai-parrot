import pytest
from pydantic import BaseModel, Field

from parrot.tools.abstract import AbstractTool
from parrot.mcp.server_base import MCPServerBase, LocalServerConfig


class EchoInput(BaseModel):
    text: str = Field(..., description="Text to echo")


class EchoTool(AbstractTool):
    """Echo input back"""
    name = "echo"
    description = "Echo input back"
    args_schema = EchoInput
    async def _execute(self, text: str) -> str:
        return text


class ConcreteMCPServer(MCPServerBase):
    async def start(self): pass
    async def stop(self): pass


class TestMCPServerBase:
    def test_register_tool(self):
        server = ConcreteMCPServer(LocalServerConfig(name="test"))
        server.register_tool(EchoTool())
        assert "echo" in server.tools

    @pytest.mark.asyncio
    async def test_handle_initialize(self):
        server = ConcreteMCPServer(LocalServerConfig(name="test", version="1.0"))
        result = await server.handle_initialize({})
        assert result["protocolVersion"] == "2024-11-05"
        assert result["serverInfo"]["name"] == "test"

    @pytest.mark.asyncio
    async def test_handle_tools_list(self):
        server = ConcreteMCPServer(LocalServerConfig())
        server.register_tool(EchoTool())
        result = await server.handle_tools_list({})
        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "echo"

    @pytest.mark.asyncio
    async def test_handle_tools_call(self):
        server = ConcreteMCPServer(LocalServerConfig())
        server.register_tool(EchoTool())
        result = await server.handle_tools_call({"name": "echo", "arguments": {"text": "hi"}})
        assert result["isError"] is False

    @pytest.mark.asyncio
    async def test_handle_tools_call_unknown(self):
        server = ConcreteMCPServer(LocalServerConfig())
        with pytest.raises(RuntimeError, match="Tool not found"):
            await server.handle_tools_call({"name": "nope", "arguments": {}})
