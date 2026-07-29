"""Integration tests for FEAT-302 (TASK-1750): factory → client → response
model roundtrips, multi-round tool-use loops, combined extended-thinking +
tool-use, and streaming chunk validation. All AWS calls are mocked — no
real network access is used.
"""
from unittest.mock import AsyncMock, patch

import pytest

from parrot.clients.bedrock import BedrockConverseClient
from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.models.responses import AIMessage


class TestBedrockIntegration:
    @pytest.mark.asyncio
    async def test_factory_to_client_roundtrip(self):
        """Factory resolves bedrock-converse → client → ask → AIMessage."""
        resolver = SUPPORTED_CLIENTS["bedrock-converse"]
        client_cls = resolver() if callable(resolver) and not isinstance(resolver, type) else resolver
        client = client_cls(model="claude-sonnet-4-5")
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "integrated!"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        with patch.object(client, 'get_client', return_value=AsyncMock()), \
             patch.object(client, '_sdk_create', return_value=response):
            result = await client.ask("test")
            assert result.provider == "bedrock-converse"
            assert result.output == "integrated!"

    @pytest.mark.asyncio
    async def test_multi_round_tool_loop(self):
        """Tool-use loop completes after 3 rounds of tool calls."""
        round_1 = {
            "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "tu_1", "name": "step_one", "input": {}}}
            ]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        round_2 = {
            "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "tu_2", "name": "step_two", "input": {}}}
            ]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 15, "outputTokens": 5}
        }
        round_3 = {
            "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "tu_3", "name": "step_three", "input": {}}}
            ]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 20, "outputTokens": 5}
        }
        final = {
            "output": {"message": {"role": "assistant", "content": [{"text": "All steps done."}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 25, "outputTokens": 10}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', side_effect=[round_1, round_2, round_3, final]):
            with patch.object(client, '_execute_tool', return_value="ok"):
                result = await client.ask("Do three steps", use_tools=True)
                assert result.output == "All steps done."
                assert len(result.tool_calls) == 3
                assert [tc.name for tc in result.tool_calls] == [
                    "step_one", "step_two", "step_three"
                ]

    @pytest.mark.asyncio
    async def test_extended_thinking_with_tool_use(self):
        """Extended thinking combined with a tool-use round — reasoningContent
        signature must survive into the follow-up request."""
        thinking_and_tool = {
            "output": {"message": {"role": "assistant", "content": [
                {"reasoningContent": {
                    "reasoningText": {"text": "I should check the weather."},
                    "signature": "sig_combo_1"
                }},
                {"toolUse": {"toolUseId": "tu_1", "name": "get_weather", "input": {"city": "NYC"}}}
            ]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 40, "outputTokens": 20}
        }
        final = {
            "output": {"message": {"role": "assistant", "content": [{"text": "It's sunny in NYC."}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 50, "outputTokens": 10}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        captured = []

        async def fake_create(payload):
            captured.append(payload)
            return thinking_and_tool if len(captured) == 1 else final

        with patch.object(client, '_sdk_create', side_effect=fake_create):
            with patch.object(client, '_execute_tool', return_value="Sunny"):
                result = await client.ask(
                    "Weather in NYC?", use_tools=True, thinking_budget=2048
                )
                assert result.output == "It's sunny in NYC."

        assert captured[0]["additionalModelRequestFields"]["thinking"]["budget_tokens"] == 2048
        assistant_turn = next(m for m in captured[1]["messages"] if m["role"] == "assistant")
        reasoning = [b for b in assistant_turn["content"] if "reasoningContent" in b]
        assert reasoning[0]["reasoningContent"]["signature"] == "sig_combo_1"

    @pytest.mark.asyncio
    async def test_streaming_chunk_validation(self):
        """ask_stream() yields well-formed str chunks followed by a single
        AIMessage sentinel with the concatenated text and correct usage."""
        client = BedrockConverseClient(model="claude-sonnet-4-5")

        async def fake_stream(_payload):
            async def _events():
                for chunk in ("The ", "quick ", "brown ", "fox."):
                    yield {"contentBlockDelta": {"delta": {"text": chunk}}}
                yield {"messageStop": {"stopReason": "end_turn"}}
                yield {"metadata": {"usage": {"inputTokens": 12, "outputTokens": 8}}}
            return _events()

        with patch.object(client, '_sdk_stream', side_effect=fake_stream):
            received = [item async for item in client.ask_stream("Tell me something")]

        *text_chunks, sentinel = received
        assert all(isinstance(c, str) for c in text_chunks)
        assert "".join(text_chunks) == "The quick brown fox."
        assert isinstance(sentinel, AIMessage)
        assert sentinel.output == "The quick brown fox."
        assert sentinel.usage.prompt_tokens == 12
        assert sentinel.usage.completion_tokens == 8

    @pytest.mark.parametrize("stop_reason", [
        "end_turn", "max_tokens", "stop_sequence", "guardrail_intervened"
    ])
    @pytest.mark.asyncio
    async def test_stop_reasons_terminate_loop(self, stop_reason):
        """Any non-``tool_use`` stopReason ends the loop after one round."""
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "done"}]}},
            "stopReason": stop_reason,
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=response) as mock_create:
            result = await client.ask("test")
            assert result.stop_reason == stop_reason
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_reason_tool_use_continues_loop(self):
        """A ``tool_use`` stopReason triggers a second round."""
        tool_response = {
            "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "tu_1", "name": "noop", "input": {}}}
            ]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        final = {
            "output": {"message": {"role": "assistant", "content": [{"text": "done"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 15, "outputTokens": 5}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', side_effect=[tool_response, final]) as mock_create:
            with patch.object(client, '_execute_tool', return_value="ok"):
                result = await client.ask("test", use_tools=True)
                assert result.stop_reason == "end_turn"
                assert mock_create.call_count == 2
