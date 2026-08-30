import pytest
from pydantic import BaseModel, Field

from parrot.tools.abstract import AbstractTool
from parrot.mcp.server_base import (
    LATEST_PROTOCOL_VERSION,
    MCPServerBase,
    LocalServerConfig,
    SUPPORTED_PROTOCOL_VERSIONS,
    negotiate_protocol_version,
)


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
    @pytest.mark.parametrize("requested", SUPPORTED_PROTOCOL_VERSIONS)
    async def test_handle_initialize_echoes_supported_version(self, requested):
        server = ConcreteMCPServer(LocalServerConfig(name="test"))
        result = await server.handle_initialize({"protocolVersion": requested})
        assert result["protocolVersion"] == requested

    @pytest.mark.asyncio
    async def test_handle_initialize_unknown_version_falls_back_to_latest(self):
        server = ConcreteMCPServer(LocalServerConfig(name="test"))
        result = await server.handle_initialize({"protocolVersion": "1999-01-01"})
        assert result["protocolVersion"] == LATEST_PROTOCOL_VERSION

    def test_negotiate_protocol_version_no_version_keeps_legacy_default(self):
        assert negotiate_protocol_version(None) == "2024-11-05"

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
