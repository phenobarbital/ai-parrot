from unittest.mock import MagicMock

from parrot.clients.nova import NovaClient
from parrot.tools import tool


@tool
def get_weather(location: str) -> str:
    """Get the current weather for a location."""
    return f"sunny in {location}"


class TestToolConfiguration:
    def test_returns_none_without_tool_manager(self):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")
        client.tool_manager = None
        assert client._build_tool_configuration() is None

    def test_returns_none_with_no_tools(self):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")
        client.tool_manager = MagicMock(all_tools=MagicMock(return_value=[]))
        assert client._build_tool_configuration() is None

    def test_builds_tool_spec_from_schema(self):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")
        fake = MagicMock()
        fake.get_schema.return_value = {
            "name": "get_weather",
            "description": "Get the current weather for a location.",
            "parameters": {"type": "object",
                           "properties": {"location": {"type": "string"}}},
        }
        client.tool_manager = MagicMock(all_tools=MagicMock(return_value=[fake]))

        config = client._build_tool_configuration()
        spec = config["tools"][0]["toolSpec"]
        assert spec["name"] == "get_weather"
        assert spec["description"].startswith("Get the current weather")
        assert "json" in spec["inputSchema"]

    def test_tool_with_broken_schema_is_skipped(self):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")
        broken = MagicMock()
        broken.get_schema.side_effect = RuntimeError("boom")
        client.tool_manager = MagicMock(all_tools=MagicMock(return_value=[broken]))
        assert client._build_tool_configuration() is None

    def test_prompt_start_omits_key_when_no_tools(self):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")
        client.tool_manager = None
        frame = client._build_prompt_start("p", "matthew")
        assert "toolConfiguration" not in frame["event"]["promptStart"]

    def test_tool_definition_from_plain_tool_decorator_is_included(self):
        """Regression guard (code review): a plain @tool-decorated function —
        CLAUDE.md's canonical example — is converted by
        ToolManager.register_tool() into a ToolDefinition, which has no
        get_schema() method. _build_tool_configuration() must fall back to
        ToolDefinition's name/description/input_schema instead of silently
        dropping the tool (which would leave toolConfiguration undeclared and
        make toolUse unreachable — the exact bug this feature fixes one
        layer up)."""
        client = NovaClient(model="nova-2-sonic", region="us-east-1")
        client.tool_manager.register_tool(get_weather)

        config = client._build_tool_configuration()
        assert config is not None
        spec = config["tools"][0]["toolSpec"]
        assert spec["name"] == "get_weather"
        assert spec["description"].startswith("Get the current weather")
        assert "json" in spec["inputSchema"]
