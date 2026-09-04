"""Unit tests for VoiceSession options threading + build_frames hook
(FEAT-418, TASK-2171 — spec §3 Module 6).
"""
import asyncio

import pytest
from parrot.models.voice import LiveVoiceResponse
from parrot.models.voice import (
    AudioFormat,
    VoiceCapabilities,
    VoiceConfig,
    VoiceProvider,
    VoiceStreamOptions,
)
from parrot.voice.session import VoiceSession


def _default_voice_capabilities() -> VoiceCapabilities:
    """A VoiceCapabilities double matching VoiceConfig()'s PCM defaults.

    FEAT-418 (TASK-2172) added a construction-time audio-format preflight
    to VoiceSession — every VoiceCapable test double now needs a
    voice_capabilities property for that preflight to pass.
    """
    return VoiceCapabilities(
        provider=VoiceProvider.GOOGLE_LIVE,
        native_stt_only=True, supports_top_p=True, supports_per_call_voice=True,
        supports_per_call_inference=True, parallel_tool_execution=True,
        emits_reconnect_signal=True, supports_session_resumption=True,
        max_session_seconds=None, max_output_tokens=4096,
        input_formats=frozenset({AudioFormat.PCM_16K}),
        output_formats=frozenset({AudioFormat.PCM_24K}),
        input_sample_rates=frozenset({16000}), output_sample_rates=frozenset({24000}),
        voice_catalog=frozenset({"Puck"}), default_voice="Puck",
    )


class RecordingClient:
    """VoiceCapable double that records the options it was handed."""

    def __init__(self):
        self.calls = []

    @property
    def voice_capabilities(self) -> VoiceCapabilities:
        return _default_voice_capabilities()

    async def stream_voice(self, audio_iterator, system_prompt=None,
                            session_id=None, user_id=None, options=None, **kwargs):
        self.calls.append(options)
        async for chunk in audio_iterator:
            if chunk is None:
                break
        yield LiveVoiceResponse(text="Hello", role="assistant")
        yield LiveVoiceResponse(text="", is_complete=True)


class ReconnectingRecordingClient:
    """Records options on every stream_voice() call AND signals
    reconnect_required on the first call, so a second call happens."""

    def __init__(self):
        self.calls = []

    @property
    def voice_capabilities(self) -> VoiceCapabilities:
        return _default_voice_capabilities()

    async def stream_voice(self, audio_iterator, system_prompt=None,
                            session_id=None, user_id=None, options=None, **kwargs):
        self.calls.append(options)
        async for chunk in audio_iterator:
            if chunk is None:
                break
        yield LiveVoiceResponse(
            text="response", is_complete=True,
            metadata={"reconnect_required": len(self.calls) <= 1},
        )


@pytest.fixture
def mock_send_fn():
    frames = []

    async def send(payload):
        frames.append(payload)
    send.frames = frames
    return send


class TestOptionThreading:
    @pytest.mark.asyncio
    async def test_options_forwarded(self, mock_send_fn):
        client = RecordingClient()
        session = VoiceSession(
            client=client, send_fn=mock_send_fn, system_prompt="x",
            voice_config=VoiceConfig(temperature=0.3),
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        assert client.calls[0] is not None
        assert client.calls[0].temperature == 0.3

    @pytest.mark.asyncio
    async def test_options_is_voice_stream_options_instance(self, mock_send_fn):
        client = RecordingClient()
        session = VoiceSession(
            client=client, send_fn=mock_send_fn, system_prompt="x",
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        assert isinstance(client.calls[0], VoiceStreamOptions)

    @pytest.mark.asyncio
    async def test_options_reflect_voice_config_fields(self, mock_send_fn):
        client = RecordingClient()
        config = VoiceConfig(
            temperature=0.15, max_tokens=2048, top_p=0.42,
            voice_name="Charon", language="es-ES",
        )
        session = VoiceSession(
            client=client, send_fn=mock_send_fn, system_prompt="x",
            voice_config=config,
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        opts = client.calls[0]
        assert opts.temperature == 0.15
        assert opts.max_tokens == 2048
        assert opts.top_p == 0.42
        assert opts.voice == "Charon"
        assert opts.language == "es-ES"

    @pytest.mark.asyncio
    async def test_options_survive_reconnect(self, mock_send_fn):
        """Regression: a reconnect that drops options is the bug being fixed."""
        client = ReconnectingRecordingClient()
        config = VoiceConfig(reconnect_on_limit=True, temperature=0.55)
        session = VoiceSession(
            client=client, send_fn=mock_send_fn, system_prompt="x",
            voice_config=config,
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        assert len(client.calls) >= 2
        assert all(o is not None for o in client.calls)
        assert all(o.temperature == 0.55 for o in client.calls)


class TestRelayHook:
    @pytest.mark.asyncio
    async def test_build_frames_override_used(self, mock_send_fn):
        class Custom(VoiceSession):
            def build_frames(self, resp, turn_no):
                return [{"type": "custom", "turn": turn_no}]

        session = Custom(
            client=RecordingClient(), send_fn=mock_send_fn,
            system_prompt="x",
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        custom_frames = [f for f in mock_send_fn.frames if f["type"] == "custom"]
        assert custom_frames
        # Default frame types (text/turn_complete) must NOT appear — the
        # override fully replaces frame construction for this response.
        assert not any(f["type"] in ("text", "turn_complete") for f in mock_send_fn.frames)

    @pytest.mark.asyncio
    async def test_default_frames_unchanged(self, mock_send_fn):
        """Existing frontends must see byte-identical output."""
        session = VoiceSession(
            client=RecordingClient(), send_fn=mock_send_fn,
            system_prompt="x",
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        text_frames = [f for f in mock_send_fn.frames if f["type"] == "text"]
        assert text_frames == [
            {"type": "text", "turn": 1, "text": "Hello", "role": "assistant"}
        ]
        complete_frames = [f for f in mock_send_fn.frames if f["type"] == "turn_complete"]
        assert complete_frames == [{
            "type": "turn_complete", "turn": 1,
            "reconnect_required": False, "usage": None,
        }]

    def test_build_frames_is_sync(self):
        """build_frames() is sync and returns a list (spec §3 Module 6)."""
        import inspect
        assert not inspect.iscoroutinefunction(VoiceSession.build_frames)

    def test_build_frames_returns_list(self):
        session = VoiceSession(
            client=RecordingClient(), send_fn=lambda p: None,
            system_prompt="x",
        )
        resp = LiveVoiceResponse(text="hi", role="assistant")
        frames = session.build_frames(resp, 1)
        assert isinstance(frames, list)
        assert frames == [{"type": "text", "turn": 1, "text": "hi", "role": "assistant"}]

    def test_build_frames_error_short_circuits(self):
        """Matches _relay()'s old early-return: an error frame replaces
        all other output for that response."""
        session = VoiceSession(
            client=RecordingClient(), send_fn=lambda p: None,
            system_prompt="x",
        )
        resp = LiveVoiceResponse(
            text="ignored", is_complete=True, metadata={"error": "boom"},
        )
        frames = session.build_frames(resp, 1)
        assert frames == [{"type": "error", "turn": 1, "message": "boom"}]
