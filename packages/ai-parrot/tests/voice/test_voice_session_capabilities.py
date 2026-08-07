"""Unit tests for VoiceSession capability preflight + capability_notice
frames (FEAT-418, TASK-2172 — spec §3 Module 6).
"""
import asyncio

import pytest
from parrot.clients.live import LiveVoiceResponse
from parrot.models.voice import (
    AudioFormat,
    VoiceCapabilities,
    VoiceConfig,
    VoiceProvider,
)
from parrot.voice.session import VoiceSession


def _capabilities(**overrides) -> VoiceCapabilities:
    """A VoiceCapabilities double; override any field for a given test."""
    defaults = {
        "provider": VoiceProvider.GOOGLE_LIVE,
        "native_stt_only": True, "supports_top_p": True, "supports_per_call_voice": True,
        "supports_per_call_inference": True, "parallel_tool_execution": True,
        "emits_reconnect_signal": True, "supports_session_resumption": True,
        "max_session_seconds": None, "max_output_tokens": 4096,
        "input_formats": frozenset({AudioFormat.PCM_16K}),
        "output_formats": frozenset({AudioFormat.PCM_24K}),
        "input_sample_rates": frozenset({16000}), "output_sample_rates": frozenset({24000}),
        "voice_catalog": frozenset({"Puck"}), "default_voice": "Puck",
    }
    defaults.update(overrides)
    return VoiceCapabilities(**defaults)


class _Client:
    """VoiceCapable double with a configurable descriptor."""

    def __init__(self, capabilities: VoiceCapabilities):
        self._capabilities = capabilities
        # Records each stream_voice() call's stt_only/options so tests can
        # assert what VoiceSession actually forwards, not just how it
        # behaves — both real clients (GeminiLiveClient, NovaAudio) read
        # stt_only ONLY from this dedicated kwarg, never from `options`
        # (code-review finding, FEAT-418).
        self.stream_voice_calls: list = []

    @property
    def voice_capabilities(self) -> VoiceCapabilities:
        return self._capabilities

    async def stream_voice(self, audio_iterator, system_prompt=None,
                            session_id=None, user_id=None, stt_only=False,
                            options=None, **kwargs):
        self.stream_voice_calls.append({"stt_only": stt_only, "options": options})
        async for chunk in audio_iterator:
            if chunk is None:
                break
        yield LiveVoiceResponse(text="response", role="assistant", is_complete=True)


@pytest.fixture
def standard_client():
    """Declares exactly VoiceConfig()'s PCM defaults — both real providers."""
    return _Client(_capabilities())


@pytest.fixture
def pcm24_only_client():
    """A client that only accepts 24k PCM for input (mismatched with
    VoiceConfig()'s 16k default)."""
    return _Client(_capabilities(
        input_formats=frozenset({AudioFormat.PCM_24K}),
        input_sample_rates=frozenset({24000}),
    ))


@pytest.fixture
def nova_like_client():
    """native_stt_only=False, mirroring Nova's real descriptor."""
    return _Client(_capabilities(
        provider=VoiceProvider.NOVA, native_stt_only=False,
        voice_catalog=frozenset({"matthew"}), default_voice="matthew",
    ))


@pytest.fixture
def mock_send_fn():
    frames = []

    async def send(payload):
        frames.append(payload)
    send.frames = frames
    return send


class TestFormatPreflight:
    def test_mismatch_raises_at_construction(self, mock_send_fn, pcm24_only_client):
        with pytest.raises(ValueError, match="format"):
            VoiceSession(
                pcm24_only_client, send_fn=mock_send_fn, system_prompt="x",
                voice_config=VoiceConfig(input_format=AudioFormat.PCM_16K),
            )

    def test_mismatch_names_both_sides(self, mock_send_fn, pcm24_only_client):
        """Checked before input_sample_rate — input_format is the first
        mismatch in _preflight_audio_formats()'s check order."""
        with pytest.raises(ValueError) as exc_info:
            VoiceSession(
                pcm24_only_client, send_fn=mock_send_fn, system_prompt="x",
            )
        message = str(exc_info.value)
        assert "input_format" in message
        assert "PCM_16K" in message
        assert "PCM_24K" in message

    def test_sample_rate_mismatch_named(self, mock_send_fn):
        """A client whose formats match but sample rates don't still
        raises, naming the sample-rate mismatch specifically."""
        client = _Client(_capabilities(input_sample_rates=frozenset({8000})))
        with pytest.raises(ValueError) as exc_info:
            VoiceSession(client, send_fn=mock_send_fn, system_prompt="x")
        message = str(exc_info.value)
        assert "input_sample_rate" in message
        assert "16000" in message
        assert "8000" in message

    def test_matching_formats_ok(self, mock_send_fn, standard_client):
        VoiceSession(standard_client, send_fn=mock_send_fn, system_prompt="x")

    def test_matching_output_format_ok(self, mock_send_fn, standard_client):
        VoiceSession(
            standard_client, send_fn=mock_send_fn, system_prompt="x",
            voice_config=VoiceConfig(output_format=AudioFormat.PCM_24K),
        )


class TestCapabilityNotices:
    @pytest.mark.asyncio
    async def test_stt_only_on_nova_notifies_not_raises(self, mock_send_fn, nova_like_client):
        session = VoiceSession(
            nova_like_client, send_fn=mock_send_fn, system_prompt="x",
            voice_config=VoiceConfig(provider="nova"), stt_only=True,
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        assert any(f["type"] == "capability_notice" for f in mock_send_fn.frames)

    @pytest.mark.asyncio
    async def test_notice_names_capability_and_provider(self, mock_send_fn, nova_like_client):
        session = VoiceSession(
            nova_like_client, send_fn=mock_send_fn, system_prompt="x",
            voice_config=VoiceConfig(provider="nova"), stt_only=True,
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        notice = next(f for f in mock_send_fn.frames if f["type"] == "capability_notice")
        assert notice["capability"] == "stt_only"
        assert notice["provider"] == "nova"
        assert notice["session_id"] == session.session_id
        assert "message" in notice

    @pytest.mark.asyncio
    async def test_notice_emitted_once_per_session(self, mock_send_fn, nova_like_client):
        session = VoiceSession(
            nova_like_client, send_fn=mock_send_fn, system_prompt="x",
            voice_config=VoiceConfig(provider="nova"), stt_only=True,
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        # Second turn on the same session — must NOT notify again.
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        notices = [f for f in mock_send_fn.frames if f["type"] == "capability_notice"]
        assert len(notices) == 1

    @pytest.mark.asyncio
    async def test_supported_knob_silent(self, mock_send_fn, standard_client):
        """Gemini natively supports stt_only — no notice should fire."""
        session = VoiceSession(
            standard_client, send_fn=mock_send_fn, system_prompt="x",
            stt_only=True,
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        assert not [f for f in mock_send_fn.frames if f["type"] == "capability_notice"]

    @pytest.mark.asyncio
    async def test_stt_only_false_no_notice_even_on_nova(self, mock_send_fn, nova_like_client):
        session = VoiceSession(
            nova_like_client, send_fn=mock_send_fn, system_prompt="x",
            voice_config=VoiceConfig(provider="nova"),
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        assert not [f for f in mock_send_fn.frames if f["type"] == "capability_notice"]

    @pytest.mark.asyncio
    async def test_stt_only_does_not_raise_on_nova(self, mock_send_fn, nova_like_client):
        """Resolved decision (spec §7): stt_only on Nova must never raise."""
        session = VoiceSession(
            nova_like_client, send_fn=mock_send_fn, system_prompt="x",
            voice_config=VoiceConfig(provider="nova"), stt_only=True,
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        assert not [f for f in mock_send_fn.frames if f["type"] == "error"]


class TestSttOnlyForwardedToClient:
    """Regression coverage for a code-review finding (FEAT-418): both real
    clients (``GeminiLiveClient.stream_voice``, ``NovaAudio.stream_voice``)
    read ``stt_only`` ONLY from their dedicated keyword argument — never
    from ``options.stt_only`` — so ``VoiceSession._run_turn()`` must pass
    ``stt_only=self.stt_only`` explicitly on every call, not rely on it
    being folded into the projected ``VoiceStreamOptions``. Before this
    fix, a bare ``VoiceSession`` wrapping a real client directly (e.g.
    ``examples/clients/nova/audio.py``'s pattern) silently ran full-duplex
    regardless of the ``stt_only=True`` constructor argument.
    """

    @pytest.mark.asyncio
    async def test_stt_only_true_reaches_dedicated_kwarg(self, mock_send_fn, standard_client):
        session = VoiceSession(
            standard_client, send_fn=mock_send_fn, system_prompt="x",
            stt_only=True,
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        assert standard_client.stream_voice_calls
        assert all(
            call["stt_only"] is True for call in standard_client.stream_voice_calls
        )

    @pytest.mark.asyncio
    async def test_stt_only_false_reaches_dedicated_kwarg(self, mock_send_fn, standard_client):
        session = VoiceSession(
            standard_client, send_fn=mock_send_fn, system_prompt="x",
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        assert standard_client.stream_voice_calls
        assert all(
            call["stt_only"] is False for call in standard_client.stream_voice_calls
        )

    @pytest.mark.asyncio
    async def test_options_stt_only_still_consistent_with_kwarg(self, mock_send_fn, standard_client):
        """Both the dedicated kwarg AND the projected options object must
        agree — a future client that reads either one gets the right
        answer."""
        session = VoiceSession(
            standard_client, send_fn=mock_send_fn, system_prompt="x",
            stt_only=True,
        )
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        call = standard_client.stream_voice_calls[0]
        assert call["stt_only"] is True
        assert call["options"].stt_only is True
