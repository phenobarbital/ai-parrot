"""
Unit tests for SupertonicTTSBackend (TASK-1510, FEAT-231).

Tests cover:
- TTSConfig accepts the new "supertonic" backend.
- VoiceSynthesizer._get_backend() dispatches to SupertonicTTSBackend
  (lazily, without loading ONNX).
- synthesize() returns a playable WAV container with a truthful mime_format.
- mime_format is always reported as audio/wav (label matches bytes).
- empty text raises ValueError.
- a missing/unconfigured model raises ValueError (no silent degradation).
"""
import wave
import io

import pytest

from parrot.voice.tts.models import SynthesisResult, TTSConfig
from parrot.voice.tts.supertonic_backend import SupertonicTTSBackend
from parrot.voice.tts.synthesizer import VoiceSynthesizer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _StubSupertonicBackend(SupertonicTTSBackend):
    """Supertonic backend with the ONNX inference stubbed out.

    Overrides ``_synthesize_sync`` to return deterministic PCM bytes so tests
    never touch onnxruntime or model weights.
    """

    def _synthesize_sync(self, text, voice, language):
        # 100 samples of 16-bit silence (200 bytes of PCM).
        return b"\x00\x00" * 100


@pytest.fixture
def supertonic_stub() -> _StubSupertonicBackend:
    """Return a Supertonic backend whose inference is stubbed."""
    return _StubSupertonicBackend(voice="default")


# ---------------------------------------------------------------------------
# Config + dispatch
# ---------------------------------------------------------------------------


def test_ttsconfig_accepts_supertonic():
    """TTSConfig validates backend='supertonic'."""
    cfg = TTSConfig(backend="supertonic")
    assert cfg.backend == "supertonic"


def test_synthesizer_dispatches_supertonic():
    """VoiceSynthesizer._get_backend() builds a SupertonicTTSBackend lazily."""
    synth = VoiceSynthesizer(TTSConfig(backend="supertonic"))
    backend = synth._get_backend()
    assert backend.__class__.__name__ == "SupertonicTTSBackend"


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


async def test_synthesize_returns_playable_container(supertonic_stub):
    """synthesize() returns a SynthesisResult with playable WAV bytes."""
    result = await supertonic_stub.synthesize(
        "Hola", mime_format="audio/wav", language="es-ES"
    )
    assert isinstance(result, SynthesisResult)
    assert result.mime_format == "audio/wav"
    assert result.audio  # non-empty

    # The bytes must be a real, parseable WAV container.
    with wave.open(io.BytesIO(result.audio), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 24000


async def test_mime_format_is_truthful_even_when_ogg_requested(supertonic_stub):
    """Requesting audio/ogg still yields audio/wav (bytes match the label)."""
    result = await supertonic_stub.synthesize("Hola", mime_format="audio/ogg")
    assert result.mime_format == "audio/wav"


async def test_empty_text_raises(supertonic_stub):
    """Empty/blank text raises ValueError before any inference."""
    with pytest.raises(ValueError):
        await supertonic_stub.synthesize("")
    with pytest.raises(ValueError):
        await supertonic_stub.synthesize("   ")


async def test_missing_deps_or_model_raises(monkeypatch):
    """A real backend with no extra/weights raises ImportError or ValueError.

    Degradation is the handler's job — the backend must surface the failure,
    never silently degrade. Whether onnxruntime is installed or not, one of
    these two errors must be raised.
    """
    monkeypatch.delenv("SUPERTONIC_MODEL_PATH", raising=False)
    backend = SupertonicTTSBackend(voice="default", model_path=None)
    with pytest.raises((ImportError, ValueError)):
        # _ensure_session imports onnxruntime (ImportError if missing) then
        # resolves the model path (ValueError if unconfigured).
        backend._ensure_session()
