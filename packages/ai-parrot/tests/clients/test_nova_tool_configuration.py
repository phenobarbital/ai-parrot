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
