"""Nova envelope + stt_only + inference-defaults tests (FEAT-418, TASK-2170).

Covers spec §3 Module 4 (envelope + inference half): canonical lowercase
role, explicit (non-filtering) stt_only acceptance, max_tokens default
change 1024 -> 4096 (with 8192 accepted), and options: VoiceStreamOptions
threading.

Follows the established mocking pattern in test_nova.py: stream_voice()'s
Pre-Alpha SDK guard is bypassed by stubbing
sys.modules['aws_sdk_bedrock_runtime'], and the bidirectional-stream thin
wrappers (_open_stream/_send_event/_iter_events) are mocked directly.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.clients.amazon.nova import NovaClient
from parrot.models.voice import VoiceStreamOptions


def _make_client(**kwargs) -> NovaClient:
    kwargs.setdefault("model", "nova-2-sonic")
    kwargs.setdefault("voice_id", "matthew")
    return NovaClient(**kwargs)


@pytest.fixture
def nova_client():
    with patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}):
        yield _make_client()


async def _empty_audio_iterator():
    return
    yield  # pragma: no cover — makes this an async generator


def _content_start(role: str):
    return {"contentStart": {"role": role}}


def _text_output(text: str):
    return {"textOutput": {"content": text}}


def _fake_events(events):
    async def _gen():
        for event in events:
            yield event

    return _gen()


class _StreamHarness:
    """Runs stream_voice() with mocked SDK wrappers, collecting the sent
    events for TestInferenceDefaults/TestOptionsThreading assertions."""

    def __init__(self, client, events):
        self.client = client
        self.events = events
        self.sent = []

    async def _send_event(self, _stream, event):
        self.sent.append(event)

    async def run(self, **kwargs):
        with (
            patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}),
            patch.object(self.client, "_open_stream", return_value=AsyncMock()),
            patch.object(self.client, "_send_event", new=self._send_event),
            patch.object(self.client, "_iter_events", return_value=_fake_events(self.events)),
        ):
            return [r async for r in self.client.stream_voice(_empty_audio_iterator(), **kwargs)]

    def session_start_config(self):
        session_start = next(e for e in self.sent if "sessionStart" in e["event"])
        return session_start["event"]["sessionStart"]["inferenceConfiguration"]

    def prompt_start_voice_id(self):
        prompt_start = next(e for e in self.sent if "promptStart" in e["event"])
        return prompt_start["event"]["promptStart"]["audioOutputConfiguration"]["voiceId"]


class TestCanonicalRole:
    @pytest.mark.asyncio
    async def test_roles_lowercased(self, nova_client):
        harness = _StreamHarness(
            nova_client,
            [
                _content_start("USER"),
                _text_output("hi"),
                _content_start("ASSISTANT"),
                _text_output("hello"),
            ],
        )
        responses = await harness.run()
        assert {r.role for r in responses if r.role} <= {"user", "assistant"}

    @pytest.mark.asyncio
    async def test_assistant_role_present(self, nova_client):
        harness = _StreamHarness(
            nova_client,
            [
                _content_start("ASSISTANT"),
                _text_output("hello there"),
            ],
        )
        responses = await harness.run()
        assert any(r.role == "assistant" for r in responses)

    @pytest.mark.asyncio
    async def test_user_role_present(self, nova_client):
        harness = _StreamHarness(
            nova_client,
            [
                _content_start("USER"),
                _text_output("what's the weather"),
            ],
        )
        responses = await harness.run()
        assert any(r.role == "user" for r in responses)


class TestSttOnly:
    @pytest.mark.asyncio
    async def test_accepted_without_raising(self, nova_client):
        harness = _StreamHarness(nova_client, [])
        await harness.run(stt_only=True)

    @pytest.mark.asyncio
    async def test_model_response_still_delivered(self, nova_client):
        """Resolved decision: Nova cannot suppress generation; do not fake it."""
        harness = _StreamHarness(
            nova_client,
            [
                _content_start("ASSISTANT"),
                _text_output("still talking"),
            ],
        )
        responses = await harness.run(stt_only=True)
        assert any(r.role == "assistant" for r in responses)

    @pytest.mark.asyncio
    async def test_logs_once_not_per_frame(self, nova_client, caplog):
        harness = _StreamHarness(
            nova_client,
            [
                _content_start("ASSISTANT"),
                _text_output("a"),
                _text_output("b"),
                _text_output("c"),
            ],
        )
        with caplog.at_level("INFO"):
            await harness.run(stt_only=True)
        stt_only_logs = [r for r in caplog.records if "stt_only" in r.message]
        assert len(stt_only_logs) == 1

    def test_capabilities_declare_non_native(self, nova_client):
        assert nova_client.voice_capabilities.native_stt_only is False


class TestInferenceDefaults:
    @pytest.mark.asyncio
    async def test_max_tokens_defaults_to_4096(self, nova_client):
        harness = _StreamHarness(nova_client, [])
        await harness.run()
        assert harness.session_start_config()["maxTokens"] == 4096

    @pytest.mark.asyncio
    async def test_8192_accepted(self, nova_client):
        harness = _StreamHarness(nova_client, [])
        await harness.run(max_tokens=8192)
        assert harness.session_start_config()["maxTokens"] == 8192

    def test_descriptor_max_output_tokens(self, nova_client):
        assert nova_client.voice_capabilities.max_output_tokens == 8192


class TestOptionsThreading:
    @pytest.mark.asyncio
    async def test_options_temperature_max_tokens_top_p_applied(self, nova_client):
        harness = _StreamHarness(nova_client, [])
        options = VoiceStreamOptions(temperature=0.33, max_tokens=2048, top_p=0.55)
        await harness.run(options=options)
        cfg = harness.session_start_config()
        assert cfg["temperature"] == 0.33
        assert cfg["maxTokens"] == 2048
        assert cfg["topP"] == 0.55

    @pytest.mark.asyncio
    async def test_explicit_kwarg_wins_over_options(self, nova_client):
        harness = _StreamHarness(nova_client, [])
        options = VoiceStreamOptions(temperature=0.33)
        await harness.run(options=options, temperature=0.9)
        assert harness.session_start_config()["temperature"] == 0.9

    @pytest.mark.asyncio
    async def test_options_voice_applied(self, nova_client):
        harness = _StreamHarness(nova_client, [])
        options = VoiceStreamOptions(voice="tiffany")
        await harness.run(options=options)
        assert harness.prompt_start_voice_id() == "tiffany"

    @pytest.mark.asyncio
    async def test_explicit_voice_id_kwarg_wins_over_options(self, nova_client):
        harness = _StreamHarness(nova_client, [])
        options = VoiceStreamOptions(voice="tiffany")
        await harness.run(options=options, voice_id="amy")
        assert harness.prompt_start_voice_id() == "amy"

    @pytest.mark.asyncio
    async def test_options_parallel_tool_execution_applied(self, nova_client):
        """No direct observable side effect with zero tool calls in this
        harness — regression-guards that passing options doesn't raise."""
        harness = _StreamHarness(nova_client, [])
        options = VoiceStreamOptions(parallel_tool_execution=True)
        await harness.run(options=options)
