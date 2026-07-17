"""Unit tests for ``NovaClient`` (FEAT-315, TASK-1812 — migrated from
``test_nova_sonic.py``, FEAT-302/TASK-1748).

Unlike the deleted ``NovaSonicClient``, constructing ``NovaClient`` NEVER
requires the Pre-Alpha ``aws_sdk_bedrock_runtime`` package — the SDK guard
moved to the first ``stream_voice()`` call (TASK-1807). Bidirectional-stream
calls are still mocked via the client's thin wrappers (``_open_stream`` /
``_send_event`` / ``_iter_events``), mirroring how ``BedrockConverseClient``
tests mock ``_sdk_create`` / ``_sdk_stream``; those two thin wrappers ARE
what would import the Pre-Alpha SDK for real, so tests that exercise
``stream_voice()`` stub ``sys.modules['aws_sdk_bedrock_runtime']`` so the
lazy ``_require_voice_sdk()`` guard (called at the top of ``stream_voice()``,
before the mocked wrappers run) does not raise.

Text methods (``ask``/``ask_stream``/``invoke``/``resume``) are asserted to
be INHERITED from ``BedrockConverseBase`` — no internal delegate client
object exists post-FEAT-315 (spec §8 resolved U1).
"""
import asyncio
import base64
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.clients.nova import NovaClient


def _make_client(**kwargs) -> NovaClient:
    """Construct a NovaClient for voice tests (default model: nova-2-sonic).

    Construction itself never requires the Pre-Alpha voice SDK — unlike
    the deleted ``NovaSonicClient``, no ``sys.modules`` stubbing is needed
    here (only around ``stream_voice()`` calls, see ``nova_client`` fixture).
    """
    kwargs.setdefault("model", "nova-2-sonic")
    return NovaClient(**kwargs)


class TestNovaClientDefaults:
    def test_client_type(self):
        client = _make_client()
        assert client.client_type == "nova"
        assert client.client_name == "nova"

    def test_default_model_is_text_model(self):
        """NovaClient's class-level default model is the TEXT model
        (nova-2-lite) — voice callers must pass model="nova-2-sonic"
        explicitly (spec §3 Module 3), which _make_client() does above."""
        assert NovaClient()._default_model == "nova-2-lite"

    def test_construction_does_not_require_voice_sdk(self, monkeypatch):
        """Code-review regression guard (FEAT-315): the Pre-Alpha SDK guard
        moved from __init__ (NovaSonicClient) to stream_voice() (NovaAudio)
        so text/generation-only usage never requires it."""
        monkeypatch.setitem(sys.modules, "aws_sdk_bedrock_runtime", None)
        NovaClient()  # must not raise

    def test_pcm_format_constants(self):
        client = _make_client()
        assert client.INPUT_SAMPLE_RATE_HZ == 16000
        assert client.OUTPUT_SAMPLE_RATE_HZ == 24000

    def test_no_nova_sonic_module(self):
        """spec §5 acceptance criterion: nova_sonic.py is deleted."""
        import importlib
        with pytest.raises(ImportError):
            importlib.import_module("parrot.clients.nova_sonic")


@pytest.fixture
def nova_client():
    with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}):
        yield _make_client()


async def _fake_audio_iterator():
    yield b"\x00\x01" * 8
    yield None


async def _empty_events():
    """An event stream that yields nothing (used when a test only cares
    about what the sender task sends, not the receiver output).

    Sleeps briefly before returning so the concurrently-scheduled
    ``_audio_sender`` task gets scheduling slices to fully drain the audio
    iterator before ``stream_voice()``'s ``finally`` block cancels it.
    """
    await asyncio.sleep(0.05)
    return
    yield  # pragma: no cover — makes this an async generator


class TestStreamVoice:
    """Ported protocol tests (TASK-1807 port target) — assertions preserved
    verbatim from test_nova_sonic.py; only the client class changed."""

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

        with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}), \
             patch.object(nova_client, '_open_stream', return_value=AsyncMock()), \
             patch.object(nova_client, '_send_event', new=AsyncMock()), \
             patch.object(nova_client, '_iter_events', return_value=fake_events()):
            responses = [
                r async for r in nova_client.stream_voice(_fake_audio_iterator())
            ]

        text_responses = [r for r in responses if r.text]
        audio_responses = [r for r in responses if r.audio_data]
        # (This fixture's audioOutput content is raw bytes, not base64 text
        # — see test_stream_voice_audio_output_decodes_base64 below for the
        # real wire-format path.)
        assert text_responses[0].text == "Hello"
        assert audio_responses[0].audio_data == b"\x01\x02"
        assert responses[-1].is_complete is True

    @pytest.mark.asyncio
    async def test_stream_voice_audio_output_decodes_base64(self, nova_client):
        """Code-review regression test: audioOutputConfiguration declares
        "encoding": "base64" (stream_voice()'s promptStart event), so
        audioOutput.content arrives as a base64 *text* string over the wire
        — it must be decoded to raw bytes before reaching
        LiveVoiceResponse.audio_data (typed Optional[bytes])."""
        raw_pcm = b"\x11\x22\x33\x44"
        b64_content = base64.b64encode(raw_pcm).decode("ascii")
        events = [
            {"audioOutput": {"content": b64_content}},
            {"completionEnd": {}},
        ]

        async def fake_events():
            for e in events:
                yield e

        with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}), \
             patch.object(nova_client, '_open_stream', return_value=AsyncMock()), \
             patch.object(nova_client, '_send_event', new=AsyncMock()), \
             patch.object(nova_client, '_iter_events', return_value=fake_events()):
            responses = [
                r async for r in nova_client.stream_voice(_fake_audio_iterator())
            ]

        audio_responses = [r for r in responses if r.audio_data]
        assert audio_responses[0].audio_data == raw_pcm

    @pytest.mark.asyncio
    async def test_audio_sender_base64_encodes_pcm_chunks(self, nova_client):
        """Code-review regression test: audioInputConfiguration declares
        "encoding": "base64" (stream_voice()'s contentStart event), so
        outbound PCM chunks must be base64-text-encoded before being
        embedded in the JSON audioInput event frame."""
        raw_pcm = b"\x00\x01" * 8
        sent_events = []

        async def capture_send(_stream, event):
            sent_events.append(event)

        async def audio_iterator():
            yield raw_pcm
            yield None

        with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}), \
             patch.object(nova_client, '_open_stream', return_value=AsyncMock()), \
             patch.object(nova_client, '_send_event', new=capture_send), \
             patch.object(nova_client, '_iter_events', return_value=_empty_events()):
            async for _ in nova_client.stream_voice(audio_iterator()):
                pass

        audio_input_events = [e for e in sent_events if "audioInput" in e.get("event", {})]
        assert len(audio_input_events) == 1
        sent_content = audio_input_events[0]["event"]["audioInput"]["content"]
        assert isinstance(sent_content, str)
        assert base64.b64decode(sent_content) == raw_pcm

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

        with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}), \
             patch.object(nova_client, '_open_stream', return_value=AsyncMock()), \
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

        with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}), \
             patch.object(nova_client, '_open_stream', return_value=AsyncMock()), \
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

        with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}), \
             patch.object(nova_client, '_open_stream', return_value=AsyncMock()), \
             patch.object(nova_client, '_send_event', new=AsyncMock()), \
             patch.object(nova_client, '_iter_events', return_value=fake_events()), \
             patch('parrot.clients.nova.audio.time.monotonic', side_effect=[0, 0, 10_000]):
            responses = [
                r async for r in nova_client.stream_voice(_fake_audio_iterator())
            ]

        assert responses[-1].metadata.get("reconnect_required") is True

    @pytest.mark.asyncio
    async def test_stream_voice_per_call_voice_id_override(self, nova_client):
        """spec §8 resolved: voice_id is also readable per-call via
        stream_voice(**kwargs), falling back to the constructor default."""
        assert nova_client.voice_id == "matthew"
        sent_events = []

        async def capture_send(_stream, event):
            sent_events.append(event)

        with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}), \
             patch.object(nova_client, '_open_stream', return_value=AsyncMock()), \
             patch.object(nova_client, '_send_event', new=capture_send), \
             patch.object(nova_client, '_iter_events', return_value=_empty_events()):
            async for _ in nova_client.stream_voice(_fake_audio_iterator(), voice_id="tiffany"):
                pass

        prompt_start_events = [e for e in sent_events if "promptStart" in e.get("event", {})]
        assert prompt_start_events[0]["event"]["promptStart"][
            "audioOutputConfiguration"
        ]["voiceId"] == "tiffany"


class TestTextInheritedNotDelegated:
    """NovaClient text methods are INHERITED from BedrockConverseBase — no
    internal delegate client object exists (spec §8 resolved U1); this
    supersedes the deleted TestTextFallback/_get_text_client suite."""

    @pytest.mark.asyncio
    async def test_ask_inherited_from_bedrock_converse_base(self, nova_client):
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Hi!"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 5, "outputTokens": 5}
        }
        with patch.object(nova_client, '_sdk_create', return_value=response):
            result = await nova_client.ask("Hello")
            assert result.output == "Hi!"
            # Inherited verbatim from BedrockConverseBase.ask() — the
            # provider string is hardcoded there, NOT derived from
            # client_name, so it stays "bedrock-converse" even on NovaClient.
            assert result.provider == "bedrock-converse"

    @pytest.mark.asyncio
    async def test_ask_stream_inherited_from_bedrock_converse_base(self, nova_client):
        async def fake_stream(_payload):
            async def _events():
                yield {"contentBlockDelta": {"delta": {"text": "Hi!"}}}
                yield {"messageStop": {"stopReason": "end_turn"}}
                yield {"metadata": {"usage": {"inputTokens": 5, "outputTokens": 3}}}
            return _events()

        with patch.object(nova_client, '_sdk_stream', side_effect=fake_stream):
            chunks = [c async for c in nova_client.ask_stream("Hello")]
            assert chunks[0] == "Hi!"

    @pytest.mark.asyncio
    async def test_invoke_inherited_from_bedrock_converse_base(self, nova_client):
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "Hi!"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 5, "outputTokens": 5}
        }
        with patch.object(nova_client, '_sdk_create', return_value=response):
            result = await nova_client.invoke("Hello")
            assert result.output == "Hi!"

    @pytest.mark.asyncio
    async def test_resume_inherited_is_functional_not_notimplemented(self, nova_client):
        """Unlike the deleted NovaSonicClient.resume() (always
        NotImplementedError), NovaClient.resume() is the real
        BedrockConverseBase implementation."""
        state = {
            "messages": [{"role": "user", "content": [{"text": "hi"}]}],
            "tool_call_id": "tu_1",
        }
        response = {
            "output": {"message": {"role": "assistant", "content": [{"text": "resumed"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 5, "outputTokens": 5}
        }
        with patch.object(nova_client, '_sdk_create', return_value=response):
            result = await nova_client.resume("session-1", "input", state)
            assert result.output == "resumed"

    def test_no_internal_text_delegate(self, nova_client):
        assert not hasattr(nova_client, "_text_client")
        assert not hasattr(nova_client, "_get_text_client")


class TestPiiGuardrail:
    @pytest.mark.asyncio
    async def test_apply_pii_guardrail_no_guardrail_configured(self, nova_client):
        result = await nova_client._apply_pii_guardrail("some transcription")
        assert result == "some transcription"

    @pytest.mark.asyncio
    async def test_apply_pii_guardrail_calls_apply_guardrail_text_directly(self):
        """FEAT-315: _apply_pii_guardrail calls self.apply_guardrail_text
        directly (inherited from BedrockConverseBase) — the _get_text_client
        delegate pattern no longer exists."""
        client = _make_client(guardrail_id="gr-1", guardrail_version="1")
        with patch.object(
            client, 'apply_guardrail_text', new=AsyncMock(return_value="[REDACTED]")
        ) as mock_apply:
            result = await client._apply_pii_guardrail("my SSN is 123-45-6789")
            assert result == "[REDACTED]"
            mock_apply.assert_called_once_with("my SSN is 123-45-6789", source="INPUT")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_nova_ask_live():
    """Real integration test against us.amazon.nova-2-lite-v1:0 (spec §4).

    WARNING: makes a real AWS Bedrock call. Requires an explicit opt-in
    (``RUN_NOVA_LIVE_TEST=1``) — the mere presence of generic AWS
    credentials in the environment is NOT sufficient to opt in (those
    credentials commonly exist for unrelated AWS services in shared dev
    environments and may lack Bedrock Nova model access, which would
    otherwise fail this test with a provider-side error rather than a
    real code defect). Skipped by default (no opt-in in CI).
    """
    import os

    if not os.getenv("RUN_NOVA_LIVE_TEST"):
        pytest.skip(
            "RUN_NOVA_LIVE_TEST not set — opt-in required for real AWS "
            "Bedrock calls (see docstring)."
        )

    client = NovaClient()
    try:
        result = await client.ask("Say 'hello' and nothing else.")
    except Exception as exc:  # pragma: no cover — depends on AWS account state
        pytest.skip(
            f"Nova Bedrock model not accessible in this AWS account/region: {exc}"
        )
    assert result.output
