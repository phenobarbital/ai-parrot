"""
Tests for the Bedrock Converse API tool schema adapter.
=========================================================

Unit tests for ``ToolFormat.BEDROCK`` and
``ToolSchemaAdapter._clean_for_bedrock()`` (FEAT-302, TASK-1743).
"""
from parrot.tools.manager import ToolFormat, ToolSchemaAdapter


class TestBedrockToolFormat:
    def test_enum_exists(self):
        assert ToolFormat.BEDROCK.value == "bedrock"

    def test_clean_for_bedrock(self):
        schema = {
            "name": "get_weather",
            "description": "Get current weather",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
                "additionalProperties": False
            },
            "_tool_instance": object()
        }
        result = ToolSchemaAdapter.clean_schema_for_provider(schema, ToolFormat.BEDROCK)
        assert "toolSpec" in result
        assert result["toolSpec"]["name"] == "get_weather"
        assert result["toolSpec"]["description"] == "Get current weather"
        assert "json" in result["toolSpec"]["inputSchema"]
        assert "_tool_instance" not in str(result)

    def test_preserves_additional_properties(self):
        schema = {
            "name": "test",
            "description": "test",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False}
        }
        result = ToolSchemaAdapter.clean_schema_for_provider(schema, ToolFormat.BEDROCK)
        assert result["toolSpec"]["inputSchema"]["json"]["additionalProperties"] is False
