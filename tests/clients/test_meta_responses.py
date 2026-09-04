"""Unit tests for MetaClient's Responses API path (MetaClient-local, D1).

No live Meta API calls are made — the SDK client is mocked via
``get_client()``.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.clients.meta import MetaClient

LIVE_SHAPE = {  # captured shape from a real 200 response (spec §6)
    "status": "completed",
    "output": [
        {"type": "reasoning", "content": []},
        {"type": "message", "content": [{"type": "output_text", "text": "pong"}]},
    ],
    "usage": SimpleNamespace(
        input_tokens=12,
        output_tokens=153,
        output_tokens_details={"reasoning_tokens": 142},
    ),
}


def _sdk_with_response(**overrides):
    """Build a MagicMock SDK client whose responses.create() returns a
    MagicMock shaped like a live Responses API result.

    ``output_text`` is pinned to ``None`` explicitly — real Responses JSON
    has no such wire field (spec §6 "Does NOT Exist"); it is an
    SDK-computed convenience property. A bare ``MagicMock`` auto-vivifies
    any unset attribute access into a truthy child mock instead of
    ``None``, which would silently defeat the ``_fold_output`` fallback
    path this test suite exercises.
    """
    shape = {"output_text": None, **LIVE_SHAPE, **overrides}
    sdk = MagicMock()
    sdk.responses.create = AsyncMock(return_value=MagicMock(**shape))
    return sdk


class TestFoldOutput:
    def test_fold_ignores_reasoning_items(self):
        client = MetaClient(api_key="k")
        assert client._fold_output(LIVE_SHAPE["output"]) == "pong"

    def test_fold_concatenates_multiple_message_items(self):
        client = MetaClient(api_key="k")
        out = [
            {"type": "message", "content": [{"type": "output_text", "text": "a"}]},
            {"type": "message", "content": [{"type": "output_text", "text": "b"}]},
        ]
        assert client._fold_output(out) == "ab"

    def test_fold_empty_output_returns_empty_string(self):
        client = MetaClient(api_key="k")
        assert client._fold_output([]) == ""
        assert client._fold_output(None) == ""


class TestExtractToolCalls:
    def test_extracts_function_call_items(self):
        client = MetaClient(api_key="k")
        output = [
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "get_weather",
                "arguments": '{"city": "NYC"}',
            }
        ]
        calls = client._extract_tool_calls(output)
        assert len(calls) == 1
        assert calls[0].id == "call_1"
        assert calls[0].function.name == "get_weather"
        assert calls[0].function.arguments == '{"city": "NYC"}'

    def test_ignores_non_function_call_items(self):
        client = MetaClient(api_key="k")
        assert client._extract_tool_calls(LIVE_SHAPE["output"]) == []


class TestPrepareResponsesArgs:
    def test_lifts_system_message_into_instructions(self):
        client = MetaClient(api_key="k")
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
        ]
        req = client._prepare_responses_args(messages=messages, args={})
        assert req["instructions"] == "You are helpful."
        assert len(req["input"]) == 1
        assert req["input"][0]["role"] == "user"

    def test_sends_max_output_tokens_not_max_tokens(self):
        client = MetaClient(api_key="k")
        req = client._prepare_responses_args(
            messages=[{"role": "user", "content": "hi"}], args={"max_tokens": 999}
        )
        assert req["max_output_tokens"] == 999
        assert "max_tokens" not in req

    def test_max_output_tokens_key_wins_over_max_tokens(self):
        client = MetaClient(api_key="k")
        req = client._prepare_responses_args(
            messages=[{"role": "user", "content": "hi"}],
            args={"max_tokens": 999, "max_output_tokens": 111},
        )
        assert req["max_output_tokens"] == 111

    def test_tool_choice_always_forced_to_auto(self):
        client = MetaClient(api_key="k")
        req = client._prepare_responses_args(
            messages=[{"role": "user", "content": "hi"}],
            args={"tool_choice": "required"},
        )
        assert req["tool_choice"] == "auto"

    def test_forwards_tools(self):
        client = MetaClient(api_key="k")
        tools = [{"type": "function", "function": {"name": "f"}}]
        req = client._prepare_responses_args(
            messages=[{"role": "user", "content": "hi"}], args={"tools": tools}
        )
        assert req["tools"] == tools

    def test_tool_role_becomes_tool_output_block(self):
        client = MetaClient(api_key="k")
        messages = [
            {"role": "tool", "tool_call_id": "call_1", "name": "f", "content": "42"},
        ]
        req = client._prepare_responses_args(messages=messages, args={})
        block = req["input"][0]["content"][0]
        assert block["type"] == "tool_output"
        assert block["tool_call_id"] == "call_1"
        assert block["output"] == "42"


class TestMetaResponsesRouting:
    @pytest.mark.asyncio
    async def test_use_responses_true_calls_responses_create(self, monkeypatch):
        client = MetaClient(api_key="k", use_responses=True)
        sdk = _sdk_with_response()
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))
        await client.ask("ping")
        sdk.responses.create.assert_awaited()

    @pytest.mark.asyncio
    async def test_use_responses_false_uses_chat_funnel(self, monkeypatch):
        client = MetaClient(api_key="k", use_responses=False)

        class _FakeMessage:
            content = "hi"
            tool_calls = None

        class _FakeChoice:
            message = _FakeMessage()
            finish_reason = "stop"
            stop_reason = "stop"

        class _FakeResponse:
            choices = [_FakeChoice()]
            usage = None

            def model_dump(self):
                return {"choices": [{"message": {"content": "hi"}}]}

        funnel = AsyncMock(return_value=_FakeResponse())
        monkeypatch.setattr(client, "_chat_completion", funnel)
        await client.ask("ping")
        funnel.assert_awaited()

    @pytest.mark.asyncio
    async def test_ask_returns_folded_text(self, monkeypatch):
        client = MetaClient(api_key="k", use_responses=True)
        sdk = _sdk_with_response()
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))
        result = await client.ask("ping")
        assert result.output == "pong"

    @pytest.mark.asyncio
    async def test_sends_max_output_tokens_on_the_wire(self, monkeypatch):
        client = MetaClient(api_key="k", use_responses=True)
        sdk = _sdk_with_response()
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))
        await client.ask("ping", max_tokens=321)
        _, kwargs = sdk.responses.create.call_args
        assert kwargs["max_output_tokens"] == 321
        assert "max_tokens" not in kwargs

    @pytest.mark.asyncio
    async def test_tool_calling_round_trip(self, monkeypatch):
        """A function_call in round 1 is executed and round 2 answers."""
        client = MetaClient(api_key="k", use_responses=True)
        sdk = MagicMock()
        round1 = MagicMock(
            status="completed",
            output=[
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "get_weather",
                    "arguments": '{"city": "NYC"}',
                }
            ],
            usage=None,
        )
        round1.output_text = None
        round2 = MagicMock(
            status="completed",
            output=[
                {"type": "message", "content": [{"type": "output_text", "text": "It's sunny."}]}
            ],
            usage=None,
        )
        round2.output_text = None
        sdk.responses.create = AsyncMock(side_effect=[round1, round2])
        monkeypatch.setattr(client, "get_client", AsyncMock(return_value=sdk))

        async def fake_execute_tool(name, args):
            assert name == "get_weather"
            return "sunny"

        monkeypatch.setattr(client, "_execute_tool", fake_execute_tool)

        result = await client.ask("What's the weather in NYC?")

        assert sdk.responses.create.await_count == 2
        assert result.output == "It's sunny."
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_weather"
