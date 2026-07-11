"""Error-handling and edge-case tests for FEAT-302 (TASK-1750):
ThrottlingException retry, ValidationException propagation, streaming
errors, missing ``aioboto3``, invalid model IDs, and response-shape edge
cases (empty/reasoning-only/multi-block content). All AWS calls are
mocked — no real network access is used.
"""
import sys

import pytest
from unittest.mock import patch

from parrot.clients.bedrock import BedrockConverseClient


class TestBedrockErrors:
    def test_import_error_without_aioboto3(self):
        """get_client() raises ImportError when aioboto3 cannot be imported."""
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.dict(sys.modules, {"aioboto3": None}):
            with pytest.raises(ImportError):
                import asyncio
                asyncio.run(client.get_client())

    @pytest.mark.asyncio
    async def test_throttling_exception_triggers_fallback_retry(self):
        """A ThrottlingException-shaped error on the first call triggers a
        retry against the configured fallback model.

        Note: ``AbstractClient.__init__`` always sets
        ``self._fallback_model = kwargs.get('fallback_model', None)``, which
        would otherwise shadow the class-level default
        (``"claude-haiku-4-5"``) with ``None`` for a normally-constructed
        client — pre-existing base-class behavior (also affects
        ``AnthropicClient``). Fixed locally (code review follow-up) via
        ``kwargs.setdefault('fallback_model', self._fallback_model)`` in
        ``BedrockConverseClient.__init__`` — see
        ``test_bedrock_converse.py::test_fallback_model_defaults_without_explicit_kwarg``.
        The explicit ``fallback_model=`` kwarg below is now redundant (kept
        for clarity/documentation of intent) rather than required.
        """

        class ThrottlingException(Exception):
            pass

        final_response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok via fallback"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        client = BedrockConverseClient(
            model="claude-sonnet-4-5", fallback_model="claude-haiku-4-5"
        )
        with patch.object(
            client, '_sdk_create',
            side_effect=[ThrottlingException("slow down"), final_response]
        ) as mock_create:
            result = await client.ask("Hello")
            assert result.output == "ok via fallback"
            assert result.metadata.get("used_fallback_model") is True
            assert mock_create.call_count == 2

    @pytest.mark.asyncio
    async def test_validation_exception_propagates(self):
        """A non-capacity error (e.g. ValidationException) is not retried
        and propagates to the caller unchanged."""

        class ValidationException(Exception):
            pass

        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(
            client, '_sdk_create', side_effect=ValidationException("bad request")
        ):
            with pytest.raises(ValidationException, match="bad request"):
                await client.ask("Hello")

    @pytest.mark.asyncio
    async def test_model_stream_error_propagates(self):
        """An error raised mid-stream (e.g. ModelStreamErrorException) is not
        swallowed — it propagates out of the async generator."""

        class ModelStreamErrorException(Exception):
            pass

        client = BedrockConverseClient(model="claude-sonnet-4-5")

        async def fake_stream(_payload):
            async def _events():
                yield {"contentBlockDelta": {"delta": {"text": "partial"}}}
                raise ModelStreamErrorException("stream broke")
            return _events()

        with patch.object(client, '_sdk_stream', side_effect=fake_stream):
            received = []
            with pytest.raises(ModelStreamErrorException, match="stream broke"):
                async for item in client.ask_stream("Hello"):
                    received.append(item)
            assert received == ["partial"]

    @pytest.mark.asyncio
    async def test_invalid_model_id_passes_through_with_warning(self, caplog):
        """An unrecognized model ID is not a hard error — bedrock_models.translate()
        logs a warning and passes it through unchanged."""
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 5, "outputTokens": 5}
        }
        client = BedrockConverseClient(model="totally-unknown-model-xyz")
        with patch.object(client, '_sdk_create', return_value=response) as mock_create:
            with caplog.at_level("WARNING"):
                await client.ask("Hello")
            sent_payload = mock_create.call_args[0][0]
            assert sent_payload["modelId"] == "totally-unknown-model-xyz"
            assert any("unknown public model ID" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_empty_content_blocks(self):
        """Empty content blocks return empty string output without crashing."""
        response = {
            "output": {"message": {"role": "assistant", "content": []}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 5, "outputTokens": 0}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=response):
            result = await client.ask("Hello")
            assert result.output == ""

    @pytest.mark.asyncio
    async def test_reasoning_only_response(self):
        """A response with only reasoningContent (no text block) does not
        crash and yields empty text output; reasoning is preserved in
        raw_response."""
        response = {
            "output": {"message": {"role": "assistant", "content": [
                {"reasoningContent": {
                    "reasoningText": {"text": "Just thinking, no answer yet."},
                    "signature": "sig_only"
                }}
            ]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=response):
            result = await client.ask("Hello")
            assert result.output == ""
            reasoning = [
                b for b in result.raw_response["output"]["message"]["content"]
                if "reasoningContent" in b
            ]
            assert reasoning[0]["reasoningContent"]["signature"] == "sig_only"

    @pytest.mark.asyncio
    async def test_multiple_text_blocks_concatenated(self):
        """Multiple {"text": ...} content blocks are concatenated in order."""
        response = {
            "output": {"message": {"role": "assistant", "content": [
                {"text": "Hello, "},
                {"text": "world"},
                {"text": "!"},
            ]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        with patch.object(client, '_sdk_create', return_value=response):
            result = await client.ask("Hello")
            assert result.output == "Hello, world!"

    @pytest.mark.asyncio
    async def test_very_large_tool_result(self):
        """A very large tool result string flows through the tool loop
        without truncation or error."""
        large_result = "x" * 200_000
        tool_response = {
            "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "tu_1", "name": "big_tool", "input": {}}}
            ]}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 10, "outputTokens": 5}
        }
        final_response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "done"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 15, "outputTokens": 5}
        }
        client = BedrockConverseClient(model="claude-sonnet-4-5")
        captured = []

        async def fake_create(payload):
            captured.append(payload)
            return tool_response if len(captured) == 1 else final_response

        with patch.object(client, '_sdk_create', side_effect=fake_create):
            with patch.object(client, '_execute_tool', return_value=large_result):
                result = await client.ask("Run big tool", use_tools=True)
                assert result.output == "done"

        second_payload_messages = captured[1]["messages"]
        tool_result_msg = next(
            m for m in second_payload_messages
            if m["role"] == "user" and any("toolResult" in b for b in m["content"])
        )
        tool_result_block = next(b for b in tool_result_msg["content"] if "toolResult" in b)
        assert len(tool_result_block["toolResult"]["content"][0]["text"]) == 200_000
