import pytest
from pydantic import BaseModel, Field
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.mcp.adapter import MCPToolAdapter
from parrot.mcp.resources import MCPResource


class EchoInput(BaseModel):
    text: str = Field(..., description="Text to echo")

class EchoTool(AbstractTool):
    """Echo input back"""
    name = "echo"
    description = "Echo input back"
    args_schema = EchoInput
    async def _execute(self, text: str) -> str:
        return text


class TestMCPToolAdapter:
    def test_to_mcp_definition(self):
        adapter = MCPToolAdapter(EchoTool())
        defn = adapter.to_mcp_tool_definition()
        assert defn["name"] == "echo"
        assert defn["description"] == "Echo input back"
        assert "properties" in defn["inputSchema"]

    @pytest.mark.asyncio
    async def test_execute_success(self):
        adapter = MCPToolAdapter(EchoTool())
        result = await adapter.execute({"text": "hello"})
        assert result["isError"] is False
        assert any("hello" in c["text"] for c in result["content"])

    @pytest.mark.asyncio
    async def test_execute_error(self):
        class FailTool(AbstractTool):
            name = "fail"
            description = "Always fails"
            args_schema = EchoInput
            async def _execute(self, **kwargs):
                raise ValueError("boom")
        adapter = MCPToolAdapter(FailTool())
        result = await adapter.execute({"text": "x"})
        assert result["isError"] is True


class TestMCPResource:
    def test_to_dict(self):
        r = MCPResource(uri="file:///test", name="test", description="A test")
        d = r.to_dict()
        assert d["uri"] == "file:///test"
        assert d["name"] == "test"
        assert d["description"] == "A test"
