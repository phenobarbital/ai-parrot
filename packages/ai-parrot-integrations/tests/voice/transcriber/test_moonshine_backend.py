"""
Unit tests for MoonshineSTTBackend (TASK-1511, FEAT-231).

Tests cover:
- The TranscriberBackend enum gains MOONSHINE.
- The default backend is unchanged (FasterWhisper).
- VoiceTranscriber._get_backend() dispatches to MoonshineSTTBackend
  (lazily, without importing the Moonshine runtime).
- transcribe(Path) returns a TranscriptionResult (inference stubbed).
- a missing audio file raises FileNotFoundError.
- a missing runtime raises ImportError (no silent degradation).
"""
import wave

import pytest

from parrot.voice.transcriber.models import (
    TranscriberBackend,
    TranscriptionResult,
    VoiceTranscriberConfig,
)
from parrot.voice.transcriber.moonshine_backend import MoonshineSTTBackend
from parrot.voice.transcriber.transcriber import VoiceTranscriber


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _StubMoonshineBackend(MoonshineSTTBackend):
    """Moonshine backend with the runtime inference stubbed out."""

    def _transcribe_sync(self, audio_path, language):
        return "hola mundo", language or "en"


@pytest.fixture
def moonshine_stub() -> _StubMoonshineBackend:
    """Return a Moonshine backend whose inference is stubbed."""
    return _StubMoonshineBackend()


def _write_wav(path) -> None:
    """Write a tiny valid mono 16 kHz WAV file to ``path``."""
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)  # 0.1 s of silence


# ---------------------------------------------------------------------------
# Enum + dispatch
# ---------------------------------------------------------------------------


def test_enum_has_moonshine():
    """TranscriberBackend gains a MOONSHINE member with the right value."""
    assert TranscriberBackend.MOONSHINE == "moonshine"


def test_default_backend_unchanged():
    """FasterWhisper remains the default backend (Moonshine is opt-in)."""
    assert VoiceTranscriberConfig().backend == TranscriberBackend.FASTER_WHISPER


def test_transcriber_dispatches_moonshine():
    """VoiceTranscriber._get_backend() builds a MoonshineSTTBackend lazily."""
    t = VoiceTranscriber(
        VoiceTranscriberConfig(backend=TranscriberBackend.MOONSHINE)
    )
    backend = t._get_backend()
    assert backend.__class__.__name__ == "MoonshineSTTBackend"


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------


async def test_transcribe_returns_result(moonshine_stub, tmp_path):
    """transcribe(Path) returns a populated TranscriptionResult."""
    wav = tmp_path / "a.wav"
    _write_wav(wav)
    result = await moonshine_stub.transcribe(wav)
    assert isinstance(result, TranscriptionResult)
    assert result.text == "hola mundo"
    assert result.language == "en"
    assert result.processing_time_ms >= 0
    assert result.duration_seconds > 0  # probed from the WAV header


async def test_missing_file_raises(moonshine_stub, tmp_path):
    """A non-existent audio file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        await moonshine_stub.transcribe(tmp_path / "nope.wav")


async def test_missing_runtime_raises(tmp_path):
    """A real backend with no Moonshine runtime raises ImportError.

    Degradation is the handler's job — the backend surfaces the failure.
    """
    wav = tmp_path / "a.wav"
    _write_wav(wav)
    backend = MoonshineSTTBackend()
    # Skip only if the runtime happens to be installed in this environment.
    runtime_present = False
    for module_name in ("moonshine_onnx", "moonshine"):
        try:
            __import__(module_name)
            runtime_present = True
            break
        except ImportError:
            continue
    if runtime_present:
        pytest.skip("Moonshine runtime is installed; cannot assert ImportError")
    with pytest.raises(ImportError):
        backend._ensure_model()
