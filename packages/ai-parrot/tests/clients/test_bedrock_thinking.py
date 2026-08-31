"""Unit tests for adaptive-thinking support in ``BedrockConverseBase``
(FEAT-482 Module 3).

``bedrock.py`` previously emitted exactly one extended-thinking shape —
``additionalModelRequestFields.thinking = {"type": "enabled",
"budget_tokens": N}`` — which returns HTTP 400 on 2026-generation
Anthropic models (Opus 5, Fable 5, Opus 4.8/4.7, Sonnet 5, Mythos 5) that
require ``{"type": "adaptive"}`` instead. This suite guards the per-model
shape selection in both ``ask()`` and ``ask_stream()``, and — most
importantly — that the legacy shape is byte-identical for every model
that is NOT in that family (the "no regression" acceptance criterion).
"""

from unittest.mock import patch

import pytest

from parrot.clients.bedrock import BedrockConverseClient, _requires_adaptive_thinking

ADAPTIVE_MODELS = [
    "us.anthropic.claude-opus-5",
    "global.anthropic.claude-fable-5",
    "anthropic.claude-opus-4-8",
    "us.anthropic.claude-opus-4-7",
    "anthropic.claude-sonnet-5",
]

BUDGET_TOKENS_MODELS = [
    "us.amazon.nova-2-lite-v1:0",
    "us.amazon.nova-pro-v1:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "anthropic.claude-sonnet-4-5-20250929-v1:0",
]


def _mock_response(text: str = "Hi!") -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 10, "outputTokens": 5},
    }


class TestRequiresAdaptiveThinkingPredicate:
    @pytest.mark.parametrize("model_id", ADAPTIVE_MODELS)
    def test_true_for_modern_anthropic(self, model_id):
        assert _requires_adaptive_thinking(model_id) is True

    @pytest.mark.parametrize("model_id", BUDGET_TOKENS_MODELS)
    def test_false_for_nova_and_older_anthropic(self, model_id):
        assert _requires_adaptive_thinking(model_id) is False

    def test_false_for_empty_or_none(self):
        assert _requires_adaptive_thinking("") is False
        assert _requires_adaptive_thinking(None) is False


class TestThinkingShapeSelection:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("model", ADAPTIVE_MODELS)
    async def test_adaptive_shape_for_modern_anthropic(self, model):
        """Modern Anthropic models get {"type": "adaptive"}, never budget_tokens."""
        client = BedrockConverseClient(model=model)
        with patch.object(client, "_sdk_create", return_value=_mock_response()) as mock_create:
            await client.ask("Question?", thinking_budget=4096)
            sent_payload = mock_create.call_args[0][0]
            assert sent_payload["additionalModelRequestFields"]["thinking"] == {"type": "adaptive"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("model", BUDGET_TOKENS_MODELS)
    async def test_budget_tokens_unchanged_for_nova(self, model):
        """NO-REGRESSION GUARD: payload is byte-identical to pre-change behavior."""
        client = BedrockConverseClient(model=model)
        with patch.object(client, "_sdk_create", return_value=_mock_response()) as mock_create:
            await client.ask("Question?", thinking_budget=4096)
            sent_payload = mock_create.call_args[0][0]
            assert sent_payload["additionalModelRequestFields"]["thinking"] == {
                "type": "enabled",
                "budget_tokens": 4096,
            }

    @pytest.mark.asyncio
    async def test_no_thinking_field_when_budget_none(self):
        """thinking_budget=None => no `thinking` key in additionalModelRequestFields."""
        client = BedrockConverseClient(model="us.anthropic.claude-opus-5")
        with patch.object(client, "_sdk_create", return_value=_mock_response()) as mock_create:
            await client.ask("Hello")
            sent_payload = mock_create.call_args[0][0]
            assert "additionalModelRequestFields" not in sent_payload

    @pytest.mark.asyncio
    async def test_ask_stream_uses_same_selection_for_adaptive_model(self):
        """ask_stream() applies the identical per-model shape as ask()."""
        client = BedrockConverseClient(model="us.anthropic.claude-opus-5")
        captured_payloads = []

        async def fake_stream(payload):
            captured_payloads.append(payload)

            async def _events():
                yield {"contentBlockDelta": {"delta": {"text": "Hi!"}}}
                yield {"messageStop": {"stopReason": "end_turn"}}
                yield {"metadata": {"usage": {"inputTokens": 5, "outputTokens": 3}}}

            return _events()

        with patch.object(client, "_sdk_stream", side_effect=fake_stream):
            async for _ in client.ask_stream("Hi", thinking_budget=4096):
                pass

        assert captured_payloads[0]["additionalModelRequestFields"]["thinking"] == {"type": "adaptive"}

    @pytest.mark.asyncio
    async def test_ask_stream_no_regression_for_nova(self):
        """NO-REGRESSION GUARD on the ask_stream() path too."""
        client = BedrockConverseClient(model="us.amazon.nova-2-lite-v1:0")
        captured_payloads = []

        async def fake_stream(payload):
            captured_payloads.append(payload)

            async def _events():
                yield {"contentBlockDelta": {"delta": {"text": "Hi!"}}}
                yield {"messageStop": {"stopReason": "end_turn"}}
                yield {"metadata": {"usage": {"inputTokens": 5, "outputTokens": 3}}}

            return _events()

        with patch.object(client, "_sdk_stream", side_effect=fake_stream):
            async for _ in client.ask_stream("Hi", thinking_budget=4096):
                pass

        assert captured_payloads[0]["additionalModelRequestFields"]["thinking"] == {
            "type": "enabled",
            "budget_tokens": 4096,
        }

    @pytest.mark.asyncio
    async def test_reasoning_content_preservation_untouched(self):
        """The reasoningContent verbatim-preservation path (bedrock.py
        ~986-988) is unaffected by the adaptive-shape branch — the tool
        loop still re-appends reasoningContent blocks with their
        signature intact for an adaptive-thinking model."""
        tool_response = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "reasoningContent": {
                                "reasoningText": {"text": "Thinking..."},
                                "signature": "sig_adaptive_1",
                            }
                        },
                        {"toolUse": {"toolUseId": "tu_1", "name": "get_weather", "input": {"city": "NYC"}}},
                    ],
                }
            },
            "stopReason": "tool_use",
            "usage": {"inputTokens": 20, "outputTokens": 10},
        }
        final_response = _mock_response("NYC is sunny.")
        client = BedrockConverseClient(model="us.anthropic.claude-opus-5")
        captured_payloads = []

        async def fake_sdk_create(payload):
            captured_payloads.append(payload)
            return tool_response if len(captured_payloads) == 1 else final_response

        with patch.object(client, "_sdk_create", side_effect=fake_sdk_create):
            with patch.object(client, "_execute_tool", return_value="Sunny, 25C"):
                result = await client.ask("What's the weather in NYC?", use_tools=True, thinking_budget=4096)
                assert result.output == "NYC is sunny."

        second_payload_messages = captured_payloads[1]["messages"]
        assistant_turn = next(m for m in second_payload_messages if m["role"] == "assistant")
        reasoning_blocks = [b for b in assistant_turn["content"] if "reasoningContent" in b]
        assert len(reasoning_blocks) == 1
        assert reasoning_blocks[0]["reasoningContent"]["signature"] == "sig_adaptive_1"
