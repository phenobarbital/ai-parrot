"""Unit tests for ``BedrockConverseClient`` advanced features
(FEAT-302, TASK-1746): extended thinking, prompt caching, schema-based
structured output, guardrails, and the ``_invoke_native()`` fallback.
"""
from unittest.mock import AsyncMock, patch

import pytest

from parrot.clients.bedrock import BedrockConverseClient


class TestExtendedThinking:
    @pytest.mark.asyncio
    async def test_thinking_budget_sent(self):
        response = {
            "output": {"message": {"role": "assistant", "content": [
                {"reasoningContent": {"reasoningText": {"text": "Let me think..."}, "signature": "sig123"}},
                {"text": "The answer is 42."}
            ]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 50, "outputTokens": 30}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=response) as mock_create:
            result = await client.ask("What is the meaning of life?", thinking_budget=4096)
            sent_payload = mock_create.call_args[0][0]
            assert sent_payload["additionalModelRequestFields"]["thinking"] == {
                "type": "enabled", "budget_tokens": 4096
            }
            assert result.output == "The answer is 42."

    @pytest.mark.asyncio
    async def test_reasoning_content_stored_in_raw_response(self):
        """reasoningContent (text + signature) is not a dedicated AIMessage
        field — it must survive intact in raw_response."""
        response = {
            "output": {"message": {"role": "assistant", "content": [
                {"reasoningContent": {"reasoningText": {"text": "Thinking..."}, "signature": "sig_xyz"}},
                {"text": "42."}
            ]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 50, "outputTokens": 30}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=response):
            result = await client.ask("Question?", thinking_budget=2048)
            content = result.raw_response["output"]["message"]["content"]
            reasoning_blocks = [b for b in content if "reasoningContent" in b]
            assert len(reasoning_blocks) == 1
            assert reasoning_blocks[0]["reasoningContent"]["signature"] == "sig_xyz"

    @pytest.mark.asyncio
    async def test_no_thinking_field_when_budget_not_set(self, ):
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Hi!"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=response) as mock_create:
            await client.ask("Hello")
            sent_payload = mock_create.call_args[0][0]
            assert "additionalModelRequestFields" not in sent_payload


class TestPromptCaching:
    @pytest.mark.asyncio
    async def test_prompt_cache_adds_cache_point_to_system(self):
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Hi!"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=response) as mock_create:
            await client.ask("Hello", system_prompt="You are helpful.", prompt_cache=True)
            sent_payload = mock_create.call_args[0][0]
            assert sent_payload["system"] == [
                {"text": "You are helpful."},
                {"cachePoint": {"type": "default"}},
            ]
            assert sent_payload["additionalModelRequestFields"]["promptCaching"] == {
                "cachePoint": {"type": "default"}
            }

    @pytest.mark.asyncio
    async def test_cache_usage_in_extra_usage(self):
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Hi!"}]}},
            "stopReason": "end_turn",
            "usage": {
                "inputTokens": 100, "outputTokens": 20,
                "cacheReadInputTokens": 80, "cacheWriteInputTokens": 20,
            }
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=response):
            result = await client.ask("Hello", prompt_cache=True)
            assert result.usage.extra_usage["cacheReadInputTokens"] == 80
            assert result.usage.extra_usage["cacheWriteInputTokens"] == 20


class TestStructuredOutput:
    @pytest.mark.asyncio
    async def test_json_schema_in_system(self):
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": '{"name": "Alice", "age": 30}'}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 20, "outputTokens": 10}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        schema = {"type": "object", "properties": {"name": {"type": "string"}, "age": {"type": "integer"}}}
        with patch.object(client, '_sdk_create', return_value=response) as mock_create:
            result = await client.ask("Who is Alice?", output_schema=schema)
            assert result.is_structured is True
            assert result.structured_output["name"] == "Alice"
            sent_payload = mock_create.call_args[0][0]
            assert "Alice" not in sent_payload["system"][0]["text"]  # schema, not answer, injected
            assert "properties" in sent_payload["system"][0]["text"]


class TestGuardrails:
    @pytest.mark.asyncio
    async def test_guardrail_config_from_constructor(self):
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Hi!"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        client = BedrockConverseClient(
            model="claude-sonnet-4-5",
            guardrail_id="gr-123",
            guardrail_version="1",
        )
        with patch.object(client, '_sdk_create', return_value=response) as mock_create:
            await client.ask("Hello")
            sent_payload = mock_create.call_args[0][0]
            assert sent_payload["guardrailConfig"] == {
                "guardrailIdentifier": "gr-123",
                "guardrailVersion": "1",
            }

    @pytest.mark.asyncio
    async def test_guardrail_config_per_call_override(self):
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Hi!"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=response) as mock_create:
            await client.ask("Hello", guardrail_id="gr-override", guardrail_version="2")
            sent_payload = mock_create.call_args[0][0]
            assert sent_payload["guardrailConfig"] == {
                "guardrailIdentifier": "gr-override",
                "guardrailVersion": "2",
            }

    @pytest.mark.asyncio
    async def test_no_guardrail_config_when_unset(self):
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Hi!"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=response) as mock_create:
            await client.ask("Hello")
            sent_payload = mock_create.call_args[0][0]
            assert "guardrailConfig" not in sent_payload

    @pytest.mark.asyncio
    async def test_apply_guardrail_text_no_guardrail_configured(self):
        """No guardrail configured — returns text unmodified without a call."""
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        result = await client.apply_guardrail_text("some text")
        assert result == "some text"

    @pytest.mark.asyncio
    async def test_apply_guardrail_text_calls_api(self):
        client = BedrockConverseClient(
            model="claude-sonnet-4-5",
            guardrail_id="gr-123",
            guardrail_version="1",
        )
        fake_client = AsyncMock()
        fake_client.apply_guardrail = AsyncMock(return_value={
            "outputs": [{"text": "redacted text"}]
        })
        with patch.object(BedrockConverseClient, 'get_client', return_value=fake_client):
            result = await client.apply_guardrail_text("sensitive text", source="INPUT")
            assert result == "redacted text"
            fake_client.apply_guardrail.assert_called_once_with(
                guardrailIdentifier="gr-123",
                guardrailVersion="1",
                source="INPUT",
                content=[{"text": {"text": "sensitive text"}}],
            )


class TestInvokeNative:
    @pytest.mark.asyncio
    async def test_invoke_native_fallback(self):
        client = BedrockConverseClient(model="claude-opus-4-8")

        fake_body = AsyncMock()
        fake_body.read = AsyncMock(return_value=b'{"content": [{"type": "text", "text": "native reply"}]}')
        fake_client = AsyncMock()
        fake_client.invoke_model = AsyncMock(return_value={"body": fake_body})

        with patch.object(BedrockConverseClient, 'get_client', return_value=fake_client):
            result = await client._invoke_native(
                messages=[{"role": "user", "content": [{"type": "text", "text": "Hi"}]}],
                model="anthropic.claude-opus-4-8-v1:0",
            )
            assert result["content"][0]["text"] == "native reply"
            fake_client.invoke_model.assert_called_once()
            call_kwargs = fake_client.invoke_model.call_args.kwargs
            assert call_kwargs["modelId"] == "anthropic.claude-opus-4-8-v1:0"
            assert "anthropic_version" in call_kwargs["body"]
