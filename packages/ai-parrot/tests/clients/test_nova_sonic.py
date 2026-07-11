"""Unit tests for ``NovaSonicClient`` (FEAT-302, TASK-1748).

``aws_sdk_bedrock_runtime`` (Pre-Alpha, Python >= 3.12 only) is not
installed in this environment. Importing ``parrot.clients.nova_sonic``
itself never requires the SDK (it is only checked lazily inside
``__init__``), so the module/class are imported once at collection time;
individual tests stub ``sys.modules['aws_sdk_bedrock_runtime']`` only
around the constructor call that needs it — this avoids repeatedly
re-triggering ``parrot.clients.live``'s ``google.genai``/``mcp`` import
chain, which is fragile to redundant re-imports in this environment
(a pydantic-generics caching quirk unrelated to this feature).

Bidirectional-stream calls are mocked via the client's thin wrappers
(``_open_stream`` / ``_send_event`` / ``_iter_events``), mirroring how
``BedrockConverseClient`` tests mock ``_sdk_create`` / ``_sdk_stream``.
"""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.clients.nova_sonic import NovaSonicClient


def _make_client(**kwargs) -> NovaSonicClient:
    """Construct a NovaSonicClient with the Pre-Alpha SDK stubbed."""
    with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}):
        return NovaSonicClient(**kwargs)


class TestNovaSonicClient:
    def test_client_type(self):
        client = _make_client(model="amazon.nova-2-sonic-v1:0")
        assert client.client_type == "nova-sonic"
        assert client.client_name == "nova-sonic"

    def test_default_model(self):
        client = _make_client()
        assert "nova" in client._default_model.lower() or "sonic" in client._default_model.lower()

    def test_import_error_when_sdk_missing(self):
        if 'aws_sdk_bedrock_runtime' in sys.modules:
            del sys.modules['aws_sdk_bedrock_runtime']
        with pytest.raises(ImportError):
            NovaSonicClient()

    def test_pcm_format_constants(self):
        client = _make_client()
        assert client.INPUT_SAMPLE_RATE_HZ == 16000
        assert client.OUTPUT_SAMPLE_RATE_HZ == 24000


@pytest.fixture
def nova_client():
    return _make_client(model="amazon.nova-2-sonic-v1:0")


async def _fake_audio_iterator():
    yield b"\x00\x01" * 8
    yield None


class TestStreamVoice:
    @pytest.mark.asyncio
    async def test_stream_voice_yields_text_and_audio(self, nova_client):
        events = [
            {"textOutput": {"content": "Hello"}},
            {"audioOutput": {"content": b"\x01\x02"}},
            {"completionEnd": {}},
        ]

        async def fake_events():
            for e in events:
                yield e

        with patch.object(nova_client, '_open_stream', return_value=AsyncMock()), \
             patch.object(nova_client, '_send_event', new=AsyncMock()), \
             patch.object(nova_client, '_iter_events', return_value=fake_events()):
            responses = [
                r async for r in nova_client.stream_voice(_fake_audio_iterator())
            ]

        text_responses = [r for r in responses if r.text]
        audio_responses = [r for r in responses if r.audio_data]
        assert text_responses[0].text == "Hello"
        assert audio_responses[0].audio_data == b"\x01\x02"
        assert responses[-1].is_complete is True

    @pytest.mark.asyncio
    async def test_stream_voice_tool_use(self, nova_client):
        events = [
            {"toolUse": {"toolUseId": "tu_1", "toolName": "get_weather", "content": {"city": "NYC"}}},
            {"completionEnd": {}},
        ]

        async def fake_events():
            for e in events:
                yield e

        sent_events = []

        async def capture_send(_stream, event):
            sent_events.append(event)

        with patch.object(nova_client, '_open_stream', return_value=AsyncMock()), \
             patch.object(nova_client, '_send_event', new=capture_send), \
             patch.object(nova_client, '_iter_events', return_value=fake_events()), \
             patch.object(nova_client, '_execute_tool', return_value="Sunny, 25C"):
            responses = [
                r async for r in nova_client.stream_voice(_fake_audio_iterator())
            ]

        # Two frames carry tool_calls: the immediate per-call response, and
        # the final turn-complete response (mirrors GeminiLiveClient, which
        # also surfaces the accumulated tool_calls_list on turn_complete).
        tool_call_responses = [r for r in responses if r.tool_calls]
        assert len(tool_call_responses) == 2
        assert not tool_call_responses[0].is_complete
        assert tool_call_responses[0].tool_calls[0].name == "get_weather"
        assert tool_call_responses[0].tool_calls[0].result == "Sunny, 25C"
        assert tool_call_responses[1].is_complete
        # A toolResult event must have been sent back to the stream.
        tool_result_events = [e for e in sent_events if "toolResult" in e.get("event", {})]
        assert len(tool_result_events) == 1
        assert tool_result_events[0]["event"]["toolResult"]["toolUseId"] == "tu_1"

    @pytest.mark.asyncio
    async def test_stream_voice_barge_in(self, nova_client):
        events = [
            {"textOutput": {"content": "partial answer"}},
            {"interruption": True},
        ]

        async def fake_events():
            for e in events:
                yield e

        with patch.object(nova_client, '_open_stream', return_value=AsyncMock()), \
             patch.object(nova_client, '_send_event', new=AsyncMock()), \
             patch.object(nova_client, '_iter_events', return_value=fake_events()):
            responses = [
                r async for r in nova_client.stream_voice(_fake_audio_iterator())
            ]

        interrupted = [r for r in responses if r.is_interrupted]
        assert len(interrupted) == 1
        assert interrupted[0].is_complete is True

    @pytest.mark.asyncio
    async def test_stream_voice_8_minute_reconnect(self, nova_client):
        """When the connection has been open past the safety-margined
        8-minute limit, the loop signals reconnect_required and stops."""

        async def fake_events():
            # Infinite generator — the loop must break on its own via the
            # connection-lifecycle check, not because the generator ends.
            while True:
                yield {"textOutput": {"content": "still talking"}}

        with patch.object(nova_client, '_open_stream', return_value=AsyncMock()), \
             patch.object(nova_client, '_send_event', new=AsyncMock()), \
             patch.object(nova_client, '_iter_events', return_value=fake_events()), \
             patch('parrot.clients.nova_sonic.time.monotonic', side_effect=[0, 0, 10_000]):
            responses = [
                r async for r in nova_client.stream_voice(_fake_audio_iterator())
            ]

        assert responses[-1].metadata.get("reconnect_required") is True


class TestTextFallback:
    @pytest.mark.asyncio
    async def test_ask_delegates_to_bedrock_converse_client(self, nova_client):
        from parrot.clients.bedrock import BedrockConverseClient
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Hi!"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 5, "outputTokens": 5}
        }
        with patch.object(BedrockConverseClient, '_sdk_create', return_value=response):
            result = await nova_client.ask("Hello")
            assert result.output == "Hi!"
            assert result.provider == "bedrock-converse"

    @pytest.mark.asyncio
    async def test_ask_stream_delegates_to_bedrock_converse_client(self, nova_client):
        from parrot.clients.bedrock import BedrockConverseClient

        async def fake_stream(_payload):
            async def _events():
                yield {"contentBlockDelta": {"delta": {"text": "Hi!"}}}
                yield {"messageStop": {"stopReason": "end_turn"}}
                yield {"metadata": {"usage": {"inputTokens": 5, "outputTokens": 3}}}
            return _events()

        with patch.object(BedrockConverseClient, '_sdk_stream', side_effect=fake_stream):
            chunks = [c async for c in nova_client.ask_stream("Hello")]
            assert chunks[0] == "Hi!"

    @pytest.mark.asyncio
    async def test_invoke_delegates_to_bedrock_converse_client(self, nova_client):
        from parrot.clients.bedrock import BedrockConverseClient
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Hi!"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 5, "outputTokens": 5}
        }
        with patch.object(BedrockConverseClient, '_sdk_create', return_value=response):
            result = await nova_client.invoke("Hello")
            assert result.output == "Hi!"

    @pytest.mark.asyncio
    async def test_resume_raises_not_implemented(self, nova_client):
        with pytest.raises(NotImplementedError):
            await nova_client.resume("session-1", "input", {})

    def test_reuses_same_internal_text_client(self, nova_client):
        """The internal BedrockConverseClient delegate is constructed once
        and reused across calls (lazy singleton)."""
        client_a = nova_client._get_text_client()
        client_b = nova_client._get_text_client()
        assert client_a is client_b


class TestPiiGuardrail:
    @pytest.mark.asyncio
    async def test_apply_pii_guardrail_no_guardrail_configured(self, nova_client):
        result = await nova_client._apply_pii_guardrail("some transcription")
        assert result == "some transcription"

    @pytest.mark.asyncio
    async def test_apply_pii_guardrail_delegates_with_input_source(self):
        client = _make_client(
            model="amazon.nova-2-sonic-v1:0",
            guardrail_id="gr-1", guardrail_version="1",
        )

        text_client = client._get_text_client()
        with patch.object(
            text_client, 'apply_guardrail_text', new=AsyncMock(return_value="[REDACTED]")
        ) as mock_apply:
            result = await client._apply_pii_guardrail("my SSN is 123-45-6789")
            assert result == "[REDACTED]"
            mock_apply.assert_called_once_with("my SSN is 123-45-6789", source="INPUT")
