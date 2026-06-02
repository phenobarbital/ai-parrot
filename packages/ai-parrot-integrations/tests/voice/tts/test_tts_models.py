"""
Unit tests for parrot.voice.tts models and AbstractTTSBackend (TASK-1407).

Tests cover:
- TTSConfig default values
- SynthesisResult holds bytes
- AbstractTTSBackend cannot be instantiated directly
- Concrete subclass satisfies the ABC contract
"""
import pytest

from parrot.voice.tts.backend import AbstractTTSBackend
from parrot.voice.tts.models import SynthesisResult, TTSConfig


# ---------------------------------------------------------------------------
# TTSConfig tests
# ---------------------------------------------------------------------------


def test_tts_config_defaults():
    """TTSConfig defaults: backend='google', mime='audio/ogg', optional None."""
    cfg = TTSConfig()
    assert cfg.backend == "google"
    assert cfg.mime_format == "audio/ogg"
    assert cfg.voice is None
    assert cfg.language is None


def test_tts_config_custom_values():
    """TTSConfig accepts all four fields."""
    cfg = TTSConfig(
        backend="google",
        voice="Charon",
        language="en-US",
        mime_format="audio/wav",
    )
    assert cfg.backend == "google"
    assert cfg.voice == "Charon"
    assert cfg.language == "en-US"
    assert cfg.mime_format == "audio/wav"


def test_tts_config_backend_literal_validation():
    """TTSConfig rejects unknown backend values."""
    with pytest.raises(Exception):
        TTSConfig(backend="unknown_backend")  # Pydantic Literal validation


# ---------------------------------------------------------------------------
# SynthesisResult tests
# ---------------------------------------------------------------------------


def test_synthesis_result_holds_bytes():
    """SynthesisResult stores audio bytes and mime_format."""
    r = SynthesisResult(audio=b"OGG...", mime_format="audio/ogg")
    assert r.audio == b"OGG..."
    assert r.mime_format == "audio/ogg"
    assert r.duration_s is None


def test_synthesis_result_with_duration():
    """SynthesisResult accepts optional duration_s."""
    r = SynthesisResult(audio=b"\x00\x01", mime_format="audio/wav", duration_s=3.5)
    assert r.duration_s == 3.5


def test_synthesis_result_requires_audio_and_mime():
    """SynthesisResult requires both audio and mime_format."""
    with pytest.raises(Exception):
        SynthesisResult(mime_format="audio/ogg")  # missing audio
    with pytest.raises(Exception):
        SynthesisResult(audio=b"bytes")  # missing mime_format


# ---------------------------------------------------------------------------
# AbstractTTSBackend tests
# ---------------------------------------------------------------------------


def test_abstract_backend_cannot_instantiate():
    """AbstractTTSBackend raises TypeError when instantiated directly."""
    with pytest.raises(TypeError):
        AbstractTTSBackend()  # abstract method 'synthesize' not implemented


@pytest.mark.asyncio
async def test_concrete_backend_contract():
    """A minimal concrete subclass satisfies the ABC contract."""

    class _Stub(AbstractTTSBackend):
        async def synthesize(
            self, text: str, *, voice=None, mime_format="audio/ogg"
        ) -> SynthesisResult:
            return SynthesisResult(audio=b"x", mime_format=mime_format)

    b = _Stub()
    res = await b.synthesize("hola")
    assert res.audio == b"x"
    assert res.mime_format == "audio/ogg"

    # default close() must not raise
    await b.close()


@pytest.mark.asyncio
async def test_concrete_backend_respects_mime_format():
    """synthesize passes mime_format through to the result."""

    class _Stub(AbstractTTSBackend):
        async def synthesize(
            self, text: str, *, voice=None, mime_format="audio/ogg"
        ) -> SynthesisResult:
            return SynthesisResult(audio=b"data", mime_format=mime_format)

    b = _Stub()
    res = await b.synthesize("hello", mime_format="audio/wav")
    assert res.mime_format == "audio/wav"
