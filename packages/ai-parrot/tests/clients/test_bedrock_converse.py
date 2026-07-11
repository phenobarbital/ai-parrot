"""Unit tests for ``BedrockConverseClient`` (FEAT-302, TASK-1745).

Mocks the aioboto3-facing seams (``_sdk_create`` / ``_sdk_stream`` /
``_execute_tool``) so no real AWS credentials or network access are
required. ``get_client()`` is exercised for real since ``aioboto3`` is
already available in this environment (client construction does not
require valid credentials or network I/O).
"""
from unittest.mock import patch

import pytest

from parrot.clients.bedrock import BedrockConverseClient
from parrot.models.responses import AIMessage


@pytest.fixture
def mock_bedrock_response():
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": "Hello!"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 10, "outputTokens": 5}
    }


class TestBedrockConverseClient:
    def test_client_type(self):
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        assert client.client_type == "bedrock-converse"
        assert client.client_name == "bedrock-converse"

    def test_default_region_fallback(self):
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        assert client._region  # resolved from conf or "us-east-1" fallback

    def test_explicit_region(self):
        client = BedrockConverseClient(model="claude-sonnet-4-5", region="eu-west-1")
        assert client._region == "eu-west-1"

    def test_fallback_model_defaults_without_explicit_kwarg(self):
        """Code-review regression test: AbstractClient.__init__ unconditionally
        sets self._fallback_model = kwargs.get('fallback_model', None), which
        would otherwise shadow the class-level default with None for every
        normally-constructed client (identically affects AnthropicClient).
        BedrockConverseClient.__init__ works around this via
        kwargs.setdefault('fallback_model', self._fallback_model)."""
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        assert client._fallback_model == "claude-haiku-4-5"

    def test_fallback_model_explicit_override_respected(self):
        client = BedrockConverseClient(
            model="claude-sonnet-4-5", fallback_model="custom-fallback"
        )
        assert client._fallback_model == "custom-fallback"

    @pytest.mark.asyncio
    async def test_ask_basic(self, mock_bedrock_response):
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=mock_bedrock_response):
            result = await client.ask("Hello")
            assert isinstance(result, AIMessage)
            assert result.output == "Hello!"
            assert result.provider == "bedrock-converse"
            assert result.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_ask_tool_use_loop(self):
        tool_response = {
            "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "tu_1", "name": "get_weather", "input": {"city": "NYC"}}}
            ]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 20, "outputTokens": 10}
        }
        final_response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "NYC is sunny."}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 30, "outputTokens": 15}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', side_effect=[tool_response, final_response]):
            with patch.object(client, '_execute_tool', return_value="Sunny, 25C"):
                result = await client.ask("What's the weather in NYC?", use_tools=True)
                assert result.output == "NYC is sunny."
                assert result.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_ask_reasoning_content_preserved(self):
        """reasoningContent blocks (with signature) must survive the tool
        loop unmodified — re-appended verbatim in the assistant turn."""
        tool_response = {
            "output": {"message": {"role": "assistant", "content": [
                {"reasoningContent": {
                    "reasoningText": {"text": "Thinking..."},
                    "signature": "sig_abc123"
                }},
                {"toolUse": {"toolUseId": "tu_2", "name": "get_weather", "input": {"city": "LA"}}}
            ]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 20, "outputTokens": 10}
        }
        final_response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "LA is sunny."}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 30, "outputTokens": 15}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        captured_payloads = []

        async def fake_sdk_create(payload):
            captured_payloads.append(payload)
            return tool_response if len(captured_payloads) == 1 else final_response

        with patch.object(client, '_sdk_create', side_effect=fake_sdk_create):
            with patch.object(client, '_execute_tool', return_value="Sunny, 20C"):
                result = await client.ask("Weather in LA?", use_tools=True)
                assert result.output == "LA is sunny."

        # Second call's messages must include the reasoningContent block
        # with its signature intact.
        second_payload_messages = captured_payloads[1]["messages"]
        assistant_turn = next(
            m for m in second_payload_messages if m["role"] == "assistant"
        )
        reasoning_blocks = [b for b in assistant_turn["content"] if "reasoningContent" in b]
        assert len(reasoning_blocks) == 1
        assert reasoning_blocks[0]["reasoningContent"]["signature"] == "sig_abc123"

    @pytest.mark.asyncio
    async def test_ask_stream_yields_chunks_then_message(self):
        client = BedrockConverseClient(model="claude-sonnet-4-5")

        async def fake_stream(_payload):
            async def _events():
                yield {"contentBlockDelta": {"delta": {"text": "Hel"}}}
                yield {"contentBlockDelta": {"delta": {"text": "lo!"}}}
                yield {"messageStop": {"stopReason": "end_turn"}}
                yield {"metadata": {"usage": {"inputTokens": 5, "outputTokens": 3}}}
            return _events()

        with patch.object(client, '_sdk_stream', side_effect=fake_stream):
            chunks = []
            async for item in client.ask_stream("Hi"):
                chunks.append(item)

            *text_chunks, final = chunks
            assert text_chunks == ["Hel", "lo!"]
            assert isinstance(final, AIMessage)
            assert final.output == "Hello!"
            assert final.provider == "bedrock-converse"
            assert final.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_resume(self):
        final_response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Done."}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 15, "outputTokens": 5}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        state = {
            "messages": [{"role": "user", "content": [{"text": "What's the weather?"}]}],
            "tool_call_id": "tu_1",
        }
        with patch.object(client, '_sdk_create', return_value=final_response):
            result = await client.resume("session-1", "Sunny, 25C", state)
            assert result.output == "Done."
            assert result.session_id == "session-1"

    @pytest.mark.asyncio
    async def test_resume_does_not_mutate_caller_state(self):
        """Code-review regression test: resume() must copy state["messages"]
        rather than alias it — appending in place would corrupt the
        caller's stored state, breaking a retried resume() against the same
        saved state (same pattern pre-exists in AnthropicClient.resume())."""
        final_response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Done."}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 15, "outputTokens": 5}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        original_messages = [{"role": "user", "content": [{"text": "What's the weather?"}]}]
        state = {"messages": original_messages, "tool_call_id": "tu_1"}
        with patch.object(client, '_sdk_create', return_value=final_response):
            await client.resume("session-1", "Sunny, 25C", state)
        assert len(original_messages) == 1
        assert state["messages"] is original_messages

    @pytest.mark.asyncio
    async def test_invoke(self, mock_bedrock_response):
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=mock_bedrock_response):
            result = await client.invoke("Hello")
            assert result.output == "Hello!"
            assert result.model  # resolved via translate()

    @pytest.mark.asyncio
    async def test_model_id_translated(self, mock_bedrock_response):
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=mock_bedrock_response) as mocked:
            await client.ask("Hello")
            sent_payload = mocked.call_args[0][0]
            assert sent_payload["modelId"] == "anthropic.claude-sonnet-4-5-20250929-v1:0"

    def test_is_capacity_error_throttling(self):
        client = BedrockConverseClient(model="claude-sonnet-4-5")

        class ThrottlingException(Exception):
            pass

        assert client._is_capacity_error(ThrottlingException("slow down")) is True

    def test_is_capacity_error_client_error_shape(self):
        client = BedrockConverseClient(model="claude-sonnet-4-5")

        class FakeClientError(Exception):
            def __init__(self):
                super().__init__("boom")
                self.response = {"Error": {"Code": "ThrottlingException"}}

        assert client._is_capacity_error(FakeClientError()) is True

    def test_is_capacity_error_false_for_unrelated(self):
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        assert client._is_capacity_error(ValueError("not related")) is False
