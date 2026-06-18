"""Unit tests for FEAT-246 — LiveKit Native Voice Adapters.

Covers the 10 unit tests from the spec (section 4):
1. test_supertonic_tts_emits_frames
2. test_supertonic_tts_blank_text
3. test_transcriber_stt_recognize
4. test_transcriber_stt_tempfile_cleanup
5. test_transcriber_stt_error_degrades
6. test_whisper_and_moonshine_select_backend
7. test_resolve_stt_default_whisper
8. test_resolve_tts_default_supertonic
9. test_resolve_providers_env_override
10. test_build_session_uses_resolved_components

All tests use fakes so deepgram/cartesia/openai plugins are not required.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from livekit.rtc import AudioFrame

from parrot.voice.transcriber.backend import AbstractTranscriberBackend
from parrot.voice.transcriber.models import TranscriptionResult


# ---------------------------------------------------------------------------
# Fixtures — per spec section 4
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_pipeline():
    """Fake SupertonicPipeline: returns 1000 silent 16-bit samples."""

    class _P:
        sample_rate = 44100

        def synthesize_pcm(
            self,
            text: str,
            *,
            voice: Optional[str] = None,
            language: Optional[str] = None,
            sample_rate: Optional[int] = None,
        ) -> bytes:
            return b"\x00\x00" * 1000  # 1000 silent int16 samples

    return _P()


@pytest.fixture
def fake_backend():
    """Fake AbstractTranscriberBackend: always returns 'hello world'."""

    class _B(AbstractTranscriberBackend):
        async def transcribe(
            self, audio_path: Path, language: Optional[str] = None
        ) -> TranscriptionResult:
            return TranscriptionResult(
                text="hello world",
                language="en",
                duration_seconds=1.0,
                confidence=0.9,
                processing_time_ms=10,
            )

    return _B()


@pytest.fixture
def fake_audio_frame() -> AudioFrame:
    """A mono 16 kHz AudioFrame with 1000 silent samples (16-bit zero bytes)."""
    samples = 1000
    data = b"\x00\x00" * samples  # 16-bit zeros
    return AudioFrame(
        data=data,
        sample_rate=16000,
        num_channels=1,
        samples_per_channel=samples,
    )


@pytest.fixture
def fake_vad():
    """Minimal fake VAD accepted by stt.StreamAdapter."""
    return MagicMock(name="FakeVAD")


# ---------------------------------------------------------------------------
# Module 1 (TASK-246-001): SupertonicTTS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supertonic_tts_emits_frames(fake_pipeline):
    """synthesize() yields at least one SynthesizedAudio event; sample_rate matches pipeline."""
    from parrot.integrations.liveavatar.livekit_agent.voice_adapters import SupertonicTTS

    tts_adapter = SupertonicTTS(pipeline=fake_pipeline)
    assert tts_adapter.sample_rate == fake_pipeline.sample_rate

    stream = tts_adapter.synthesize("Hello, world!")
    frames = []
    async for audio in stream:
        frames.append(audio)

    assert len(frames) >= 1, "Expected at least one audio frame from synthesize()"
    # Verify all frames come at the right sample_rate
    for audio in frames:
        assert audio.frame.sample_rate == fake_pipeline.sample_rate


@pytest.mark.asyncio
async def test_supertonic_tts_blank_text(fake_pipeline):
    """synthesize('') yields no frames and raises no error."""
    from parrot.integrations.liveavatar.livekit_agent.voice_adapters import SupertonicTTS

    tts_adapter = SupertonicTTS(pipeline=fake_pipeline)

    for blank in ("", "   ", "\t\n"):
        stream = tts_adapter.synthesize(blank)
        frames = []
        async for audio in stream:
            frames.append(audio)
        assert frames == [], f"Expected no frames for blank text {blank!r}"


# ---------------------------------------------------------------------------
# Module 2 (TASK-246-001): _TranscriberSTT / WhisperSTT / MoonshineSTT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcriber_stt_recognize(fake_backend, fake_audio_frame):
    """_recognize_impl writes WAV, calls backend, returns FINAL_TRANSCRIPT SpeechEvent."""
    from livekit.agents import stt as lk_stt
    from parrot.integrations.liveavatar.livekit_agent.voice_adapters import _TranscriberSTT

    stt_adapter = _TranscriberSTT(fake_backend, language="en")

    event = await stt_adapter._recognize_impl(
        fake_audio_frame,
        language="en",
        conn_options=None,
    )

    assert event.type == lk_stt.SpeechEventType.FINAL_TRANSCRIPT
    assert len(event.alternatives) == 1
    assert event.alternatives[0].text == "hello world"
    assert event.alternatives[0].language == "en"


@pytest.mark.asyncio
async def test_transcriber_stt_tempfile_cleanup(fake_backend, fake_audio_frame):
    """Temp WAV file is unlinked even when backend raises an exception."""
    import tempfile

    created_paths = []
    original_named_temp_file = tempfile.NamedTemporaryFile

    class _ErrorBackend(AbstractTranscriberBackend):
        async def transcribe(
            self, audio_path: Path, language: Optional[str] = None
        ) -> TranscriptionResult:
            raise RuntimeError("backend failed")

    error_backend = _ErrorBackend()

    from parrot.integrations.liveavatar.livekit_agent.voice_adapters import _TranscriberSTT

    stt_adapter = _TranscriberSTT(error_backend)

    # Intercept NamedTemporaryFile to record what path was created
    def _capturing_ntf(**kwargs):
        fh = original_named_temp_file(**kwargs)
        created_paths.append(Path(fh.name))
        return fh

    with patch("tempfile.NamedTemporaryFile", side_effect=_capturing_ntf):
        # Should NOT raise — error degrades gracefully
        await stt_adapter._recognize_impl(fake_audio_frame, conn_options=None)

    assert len(created_paths) == 1, "Expected exactly one temp file"
    tmp_path = created_paths[0]
    assert not tmp_path.exists(), f"Temp file {tmp_path} was not cleaned up"


@pytest.mark.asyncio
async def test_transcriber_stt_error_degrades(fake_audio_frame, caplog):
    """Backend error → empty transcript SpeechEvent; exception is logged, not raised."""
    import logging

    from livekit.agents import stt as lk_stt
    from parrot.integrations.liveavatar.livekit_agent.voice_adapters import _TranscriberSTT

    class _ErrorBackend(AbstractTranscriberBackend):
        async def transcribe(
            self, audio_path: Path, language: Optional[str] = None
        ) -> TranscriptionResult:
            raise RuntimeError("deliberate test failure")

    error_backend = _ErrorBackend()
    stt_adapter = _TranscriberSTT(error_backend)

    with caplog.at_level(logging.ERROR):
        event = await stt_adapter._recognize_impl(fake_audio_frame, conn_options=None)

    assert event.type == lk_stt.SpeechEventType.FINAL_TRANSCRIPT
    assert event.alternatives[0].text == ""
    # The error should be logged
    assert any("transcription failed" in record.message.lower() for record in caplog.records)


def test_whisper_and_moonshine_select_backend():
    """WhisperSTT uses FasterWhisperBackend; MoonshineSTT uses MoonshineSTTBackend."""
    from parrot.voice.transcriber import FasterWhisperBackend
    from parrot.voice.transcriber.moonshine_backend import MoonshineSTTBackend
    from parrot.integrations.liveavatar.livekit_agent.voice_adapters import (
        WhisperSTT,
        MoonshineSTT,
    )

    whisper_stt = WhisperSTT(model_size="tiny")
    moonshine_stt = MoonshineSTT(model_name="moonshine/base")

    # The underlying _backend attribute should be the right type
    assert isinstance(whisper_stt._backend, FasterWhisperBackend)
    assert isinstance(moonshine_stt._backend, MoonshineSTTBackend)


# ---------------------------------------------------------------------------
# Module 3 (TASK-246-002): resolve_stt / resolve_tts
# ---------------------------------------------------------------------------


def test_resolve_stt_default_whisper(fake_vad, monkeypatch):
    """No env → resolve_stt returns StreamAdapter wrapping WhisperSTT."""
    from livekit.agents import stt as lk_stt
    from parrot.integrations.liveavatar.livekit_agent.voice_adapters import (
        resolve_stt,
    )
    from parrot.voice.transcriber import FasterWhisperBackend

    monkeypatch.delenv("LIVEAVATAR_STT_PROVIDER", raising=False)
    monkeypatch.setenv("LIVEAVATAR_WHISPER_MODEL_SIZE", "tiny")  # avoid loading large model

    result = resolve_stt(fake_vad)

    assert isinstance(result, lk_stt.StreamAdapter), f"Expected StreamAdapter, got {type(result)}"
    # The wrapped STT's _backend should be FasterWhisperBackend (WhisperSTT backed)
    assert isinstance(result.wrapped_stt._backend, FasterWhisperBackend)


def test_resolve_tts_default_supertonic(monkeypatch, tmp_path):
    """With SUPERTONIC_MODEL_DIR set to a fake dir, resolve_tts returns a TTS instance."""
    from parrot.integrations.liveavatar.livekit_agent.voice_adapters import resolve_tts
    from livekit.agents import tts as lk_tts

    monkeypatch.delenv("LIVEAVATAR_TTS_PROVIDER", raising=False)
    monkeypatch.setenv("SUPERTONIC_MODEL_DIR", str(tmp_path))

    # Patch SupertonicPipeline at the location it is imported in _build_supertonic_tts
    # (it is a local import inside the function, so we patch it in the voice.tts module)
    fake_pipeline = MagicMock()
    fake_pipeline.sample_rate = 44100

    with patch(
        "parrot.voice.tts.supertonic_inference.SupertonicPipeline",
        return_value=fake_pipeline,
    ), patch(
        "parrot.integrations.liveavatar.livekit_agent.voice_adapters._build_supertonic_tts",
    ) as mock_build:
        from parrot.integrations.liveavatar.livekit_agent.voice_adapters import SupertonicTTS
        # Return a real SupertonicTTS with the fake pipeline
        mock_build.return_value = SupertonicTTS(pipeline=fake_pipeline)
        result = resolve_tts()

    assert isinstance(result, lk_tts.TTS)
    assert result.sample_rate == 44100


def test_resolve_tts_supertonic_raises_without_model_dir(monkeypatch):
    """resolve_tts raises ValueError when SUPERTONIC_MODEL_DIR is not set."""
    from parrot.integrations.liveavatar.livekit_agent.voice_adapters import resolve_tts

    monkeypatch.delenv("LIVEAVATAR_TTS_PROVIDER", raising=False)
    monkeypatch.delenv("SUPERTONIC_MODEL_DIR", raising=False)

    with pytest.raises(ValueError, match="SUPERTONIC_MODEL_DIR"):
        resolve_tts()


def test_resolve_providers_env_override(fake_vad, monkeypatch):
    """LIVEAVATAR_*_PROVIDER selects the correct backend branches."""
    from parrot.integrations.liveavatar.livekit_agent.voice_adapters import (
        resolve_stt,
        resolve_tts,
    )
    from livekit.agents import stt as lk_stt

    # --- STT: moonshine ---
    monkeypatch.setenv("LIVEAVATAR_STT_PROVIDER", "moonshine")
    result = resolve_stt(fake_vad)
    assert isinstance(result, lk_stt.StreamAdapter)
    from parrot.voice.transcriber.moonshine_backend import MoonshineSTTBackend
    assert isinstance(result.wrapped_stt._backend, MoonshineSTTBackend)

    # --- STT: deepgram (plugin absent → ImportError with helpful message) ---
    monkeypatch.setenv("LIVEAVATAR_STT_PROVIDER", "deepgram")
    fake_deepgram = MagicMock()
    fake_deepgram.STT.return_value = MagicMock(name="deepgram.STT")
    with patch.dict("sys.modules", {"livekit.plugins.deepgram": fake_deepgram}):
        result = resolve_stt(fake_vad)
    fake_deepgram.STT.assert_called_once()

    # --- STT: openai (plugin absent → ImportError) ---
    monkeypatch.setenv("LIVEAVATAR_STT_PROVIDER", "openai")
    fake_lk_openai = MagicMock()
    fake_lk_openai.STT.return_value = MagicMock(name="lk_openai.STT")
    with patch.dict("sys.modules", {"livekit.plugins.openai": fake_lk_openai}):
        result = resolve_stt(fake_vad)
    fake_lk_openai.STT.assert_called_once()

    # --- TTS: cartesia (plugin absent → ImportError) ---
    monkeypatch.setenv("LIVEAVATAR_TTS_PROVIDER", "cartesia")
    fake_cartesia = MagicMock()
    fake_cartesia.TTS.return_value = MagicMock(name="cartesia.TTS")
    with patch.dict("sys.modules", {"livekit.plugins.cartesia": fake_cartesia}):
        result = resolve_tts()
    fake_cartesia.TTS.assert_called_once()

    # --- TTS: inference (plugin absent → ImportError) ---
    monkeypatch.setenv("LIVEAVATAR_TTS_PROVIDER", "inference")
    fake_lk_openai2 = MagicMock()
    fake_lk_openai2.TTS.return_value = MagicMock(name="lk_openai.TTS")
    with patch.dict("sys.modules", {"livekit.plugins.openai": fake_lk_openai2}):
        result = resolve_tts()
    fake_lk_openai2.TTS.assert_called_once()


def test_build_session_uses_resolved_components(monkeypatch):
    """build_session(vad) wires resolved stt/tts; explicit overrides still win."""
    from parrot.integrations.liveavatar.livekit_agent.pipeline import build_session

    # Fake components
    fake_stt = MagicMock(name="FakeSTT")
    fake_tts = MagicMock(name="FakeTTS")
    fake_vad = MagicMock(name="FakeVAD")
    fake_turn = MagicMock(name="FakeTurn")

    sessions_built = []

    def fake_session_factory(**kwargs):
        sessions_built.append(kwargs)
        return MagicMock(name="FakeSession")

    # Test 1: explicit overrides are passed unchanged
    build_session(
        fake_vad,
        stt=fake_stt,
        tts=fake_tts,
        turn_detection=fake_turn,
        session_factory=fake_session_factory,
    )
    assert len(sessions_built) == 1
    assert sessions_built[0]["stt"] is fake_stt
    assert sessions_built[0]["tts"] is fake_tts
    assert sessions_built[0]["vad"] is fake_vad

    # Test 2: defaults are resolved from env (mock resolve_stt / resolve_tts).
    # build_session imports resolve_stt/resolve_tts locally at call time,
    # so we patch them at their source module.
    sessions_built.clear()
    resolved_stt = MagicMock(name="ResolvedSTT")
    resolved_tts = MagicMock(name="ResolvedTTS")

    with patch(
        "parrot.integrations.liveavatar.livekit_agent.voice_adapters.resolve_stt",
        return_value=resolved_stt,
    ) as mock_resolve_stt, patch(
        "parrot.integrations.liveavatar.livekit_agent.voice_adapters.resolve_tts",
        return_value=resolved_tts,
    ) as mock_resolve_tts:
        build_session(
            fake_vad,
            turn_detection=fake_turn,
            session_factory=fake_session_factory,
        )

    mock_resolve_stt.assert_called_once_with(fake_vad)
    mock_resolve_tts.assert_called_once_with()
    assert sessions_built[0]["stt"] is resolved_stt
    assert sessions_built[0]["tts"] is resolved_tts
