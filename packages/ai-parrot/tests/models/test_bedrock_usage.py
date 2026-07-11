"""
Tests for Bedrock Converse API response model factory methods.
================================================================

Unit tests for ``CompletionUsage.from_bedrock()`` and
``AIMessageFactory.from_bedrock()`` (FEAT-302, TASK-1742).
"""
from parrot.models.basic import CompletionUsage, ToolCall
from parrot.models.responses import AIMessageFactory


class TestCompletionUsageFromBedrock:
    def test_basic_usage(self):
        usage = CompletionUsage.from_bedrock({"inputTokens": 100, "outputTokens": 50})
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_cache_tokens(self):
        usage = CompletionUsage.from_bedrock({
            "inputTokens": 200, "outputTokens": 100,
            "cacheReadInputTokens": 150, "cacheWriteInputTokens": 50
        })
        assert usage.extra_usage["cacheReadInputTokens"] == 150
        assert usage.extra_usage["cacheWriteInputTokens"] == 50

    def test_empty_usage(self):
        usage = CompletionUsage.from_bedrock({})
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0


class TestAIMessageFactoryFromBedrock:
    def test_text_response(self):
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Hello!"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        msg = AIMessageFactory.from_bedrock(response, "Hi", "claude-sonnet-4-5")
        assert msg.output == "Hello!"
        assert msg.provider == "bedrock-converse"
        assert msg.stop_reason == "end_turn"

    def test_tool_use_response(self):
        response = {
            "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "tu_1", "name": "get_weather", "input": {"city": "NYC"}}}
            ]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 20, "outputTokens": 10}
        }
        tool_calls = [ToolCall(id="tu_1", name="get_weather", arguments={"city": "NYC"})]
        msg = AIMessageFactory.from_bedrock(response, "Weather?", "claude-sonnet-4-5", tool_calls=tool_calls)
        assert msg.stop_reason == "tool_use"
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "get_weather"

    def test_tool_use_response_auto_extraction(self):
        """When tool_calls is not passed, from_bedrock() should extract
        ToolCall objects from ``toolUse`` content blocks automatically."""
        response = {
            "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "tu_2", "name": "get_weather", "input": {"city": "LA"}}}
            ]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 20, "outputTokens": 10}
        }
        msg = AIMessageFactory.from_bedrock(response, "Weather?", "claude-sonnet-4-5")
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].id == "tu_2"
        assert msg.tool_calls[0].name == "get_weather"
        assert msg.tool_calls[0].arguments == {"city": "LA"}
