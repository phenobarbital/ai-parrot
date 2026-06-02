"""
Unit tests for VoiceSynthesizer (TASK-1408).

Tests cover:
- Backend is lazily created on first synthesize call
- Backend is cached (same instance returned on repeated calls)
- synthesize delegates to the backend with correct voice/mime_format
- Unknown and unimplemented backends raise ValueError
- close() releases the backend
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.voice.tts.models import SynthesisResult, TTSConfig
from parrot.voice.tts.synthesizer import VoiceSynthesizer


def _make_mock_backend(audio: bytes = b"AUDIO") -> MagicMock:
    """Return a MagicMock acting as an AbstractTTSBackend."""
    backend = MagicMock()
    backend.synthesize = AsyncMock(
        return_value=SynthesisResult(audio=audio, mime_format="audio/ogg")
    )
    backend.close = AsyncMock()
    return backend


# ---------------------------------------------------------------------------
# Lazy backend creation
# ---------------------------------------------------------------------------


def test_synthesizer_lazy_backend():
    """_backend is None until the first call to _get_backend."""
    s = VoiceSynthesizer(TTSConfig(backend="google"))
    assert s._backend is None


def test_synthesizer_backend_cached():
    """_get_backend returns the same instance on repeated calls."""
    s = VoiceSynthesizer(TTSConfig(backend="google"))
    b1 = s._get_backend()
    b2 = s._get_backend()
    assert b1 is b2


def test_synthesizer_default_config():
    """VoiceSynthesizer uses TTSConfig() when no config is provided."""
    s = VoiceSynthesizer()
    assert s.config.backend == "google"
    assert s.config.mime_format == "audio/ogg"


# ---------------------------------------------------------------------------
# Backend selection errors
# ---------------------------------------------------------------------------


def test_synthesizer_rejects_elevenlabs_backend():
    """_get_backend raises ValueError for 'elevenlabs'."""
    s = VoiceSynthesizer(TTSConfig(backend="elevenlabs"))
    with pytest.raises(ValueError, match="not implemented"):
        s._get_backend()


def test_synthesizer_rejects_openai_backend():
    """_get_backend raises ValueError for 'openai'."""
    s = VoiceSynthesizer(TTSConfig(backend="openai"))
    with pytest.raises(ValueError, match="not implemented"):
        s._get_backend()


def test_synthesizer_no_backend_created_on_error():
    """_backend stays None when _get_backend raises."""
    s = VoiceSynthesizer(TTSConfig(backend="elevenlabs"))
    with pytest.raises(ValueError):
        s._get_backend()
    assert s._backend is None


# ---------------------------------------------------------------------------
# synthesize delegation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesizer_delegates_to_backend():
    """synthesize calls the backend with the configured voice and mime_format."""
    mock_backend = _make_mock_backend(b"SYNTH-AUDIO")
    s = VoiceSynthesizer(TTSConfig(backend="google", voice="Kore", mime_format="audio/wav"))
    s._backend = mock_backend  # inject mock backend

    result = await s.synthesize("Hello from the synthesizer")

    mock_backend.synthesize.assert_awaited_once_with(
        "Hello from the synthesizer",
        voice="Kore",
        mime_format="audio/wav",
        language=None,
    )
    assert result.audio == b"SYNTH-AUDIO"


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesizer_close_releases_backend():
    """close() calls backend.close() and sets _backend to None."""
    mock_backend = _make_mock_backend()
    s = VoiceSynthesizer()
    s._backend = mock_backend

    await s.close()

    mock_backend.close.assert_awaited_once()
    assert s._backend is None


@pytest.mark.asyncio
async def test_synthesizer_close_no_op_if_no_backend():
    """close() is a no-op when backend was never created."""
    s = VoiceSynthesizer()
    # Should not raise
    await s.close()
    assert s._backend is None
