"""MCPToolAdapter confirm-gate tests (Obsidian-over-MCP guarded writes)."""
import pytest

from parrot.mcp.adapter import MCPToolAdapter
from parrot.tools.abstract import AbstractTool, ToolResult

pytestmark = pytest.mark.asyncio


class _EchoTool(AbstractTool):
    name = "echo_tool"
    description = "Echo the payload."

    def __init__(self, requires_confirmation: bool = False):
        super().__init__(name=self.name, description=self.description)
        if requires_confirmation:
            self.routing_meta = {"requires_confirmation": True}
        self.calls: list[dict] = []

    async def _execute(self, **kwargs) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(result={"echo": kwargs})


class TestConfirmGate:
    def test_schema_gains_required_confirm(self):
        adapter = MCPToolAdapter(_EchoTool(requires_confirmation=True))
        definition = adapter.to_mcp_tool_definition()
        schema = definition["inputSchema"]
        assert schema["properties"]["confirm"]["type"] == "boolean"
        assert "confirm" in schema["required"]

    def test_plain_tool_schema_unchanged(self):
        adapter = MCPToolAdapter(_EchoTool())
        schema = adapter.to_mcp_tool_definition()["inputSchema"]
        assert "confirm" not in schema.get("properties", {})
        assert "confirm" not in schema.get("required", [])

    async def test_unconfirmed_call_rejected(self):
        tool = _EchoTool(requires_confirmation=True)
        adapter = MCPToolAdapter(tool)
        response = await adapter.execute({"payload": "x"})
        assert response["isError"] is True
        assert "confirm=true" in response["content"][0]["text"]
        assert tool.calls == []  # never executed

    async def test_confirm_false_rejected(self):
        tool = _EchoTool(requires_confirmation=True)
        adapter = MCPToolAdapter(tool)
        response = await adapter.execute({"payload": "x", "confirm": False})
        assert response["isError"] is True
        assert tool.calls == []

    async def test_confirmed_call_executes_without_confirm_kwarg(self):
        tool = _EchoTool(requires_confirmation=True)
        adapter = MCPToolAdapter(tool)
        response = await adapter.execute({"payload": "x", "confirm": True})
        assert response["isError"] is False
        assert tool.calls == [{"payload": "x"}]  # confirm stripped

    async def test_plain_tool_confirm_arg_stripped(self):
        tool = _EchoTool()
        adapter = MCPToolAdapter(tool)
        response = await adapter.execute({"payload": "x", "confirm": True})
        assert response["isError"] is False
        assert tool.calls == [{"payload": "x"}]
