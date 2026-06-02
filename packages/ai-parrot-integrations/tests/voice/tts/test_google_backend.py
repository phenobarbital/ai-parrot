"""
Unit tests for GoogleTTSBackend (TASK-1408).

Tests cover:
- synthesize calls generate_speech and returns audio from AIMessage.output
- synthesize raises ValueError on empty text
- synthesize raises RuntimeError when generate_speech returns no audio
- custom voice is passed through
- close() clears the client reference
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.voice.tts.google_backend import GoogleTTSBackend
from parrot.voice.tts.models import SynthesisResult


def _make_fake_message(output: bytes = b"PCM-AUDIO-BYTES") -> MagicMock:
    """Return a MagicMock resembling an AIMessage with .output set."""
    msg = MagicMock()
    msg.output = output
    return msg


def _make_mock_client(output: bytes = b"PCM-AUDIO-BYTES") -> MagicMock:
    """Return a mocked GoogleGenAIClient whose generate_speech returns fake audio."""
    client = MagicMock()
    client.generate_speech = AsyncMock(return_value=_make_fake_message(output))
    return client


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_backend_wraps_generate_speech():
    """synthesize calls generate_speech and returns a SynthesisResult."""
    client = _make_mock_client(b"PCM-AUDIO-BYTES")
    backend = GoogleTTSBackend(client=client)

    result = await backend.synthesize("hola mundo")

    client.generate_speech.assert_awaited_once()
    assert isinstance(result, SynthesisResult)
    assert result.audio == b"PCM-AUDIO-BYTES"


@pytest.mark.asyncio
async def test_google_backend_returns_correct_mime_format():
    """synthesize passes mime_format through to SynthesisResult."""
    client = _make_mock_client(b"bytes")
    backend = GoogleTTSBackend(client=client)

    result = await backend.synthesize("test", mime_format="audio/wav")

    assert result.mime_format == "audio/wav"


@pytest.mark.asyncio
async def test_google_backend_uses_custom_voice():
    """synthesize uses the custom voice when provided."""
    client = _make_mock_client()
    backend = GoogleTTSBackend(client=client, voice="Kore")

    await backend.synthesize("test with custom voice")

    # The call must have happened; we verify via call_args
    call_args = client.generate_speech.call_args
    prompt_data = call_args[0][0]  # first positional arg is the SpeechGenerationPrompt
    assert prompt_data.speakers[0].voice == "Kore"


@pytest.mark.asyncio
async def test_google_backend_uses_voice_kwarg_over_default():
    """voice= kwarg to synthesize overrides the backend's default voice."""
    client = _make_mock_client()
    backend = GoogleTTSBackend(client=client, voice="Charon")

    await backend.synthesize("override voice", voice="Puck")

    call_args = client.generate_speech.call_args
    prompt_data = call_args[0][0]
    assert prompt_data.speakers[0].voice == "Puck"


@pytest.mark.asyncio
async def test_google_backend_default_voice_charon():
    """When no voice is specified, backend defaults to 'Charon'."""
    client = _make_mock_client()
    backend = GoogleTTSBackend(client=client)

    await backend.synthesize("default voice test")

    call_args = client.generate_speech.call_args
    prompt_data = call_args[0][0]
    assert prompt_data.speakers[0].voice == "Charon"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_backend_raises_on_empty_text():
    """synthesize raises ValueError when text is empty."""
    client = _make_mock_client()
    backend = GoogleTTSBackend(client=client)

    with pytest.raises(ValueError, match="empty"):
        await backend.synthesize("")


@pytest.mark.asyncio
async def test_google_backend_raises_on_whitespace_only_text():
    """synthesize raises ValueError when text is whitespace only."""
    client = _make_mock_client()
    backend = GoogleTTSBackend(client=client)

    with pytest.raises(ValueError):
        await backend.synthesize("   ")


@pytest.mark.asyncio
async def test_google_backend_raises_when_no_audio():
    """synthesize raises RuntimeError when AIMessage.output is falsy."""
    client = _make_mock_client(output=b"")
    # Explicitly set output to None to simulate missing audio
    fake_msg = MagicMock()
    fake_msg.output = None
    client.generate_speech = AsyncMock(return_value=fake_msg)
    backend = GoogleTTSBackend(client=client)

    with pytest.raises(RuntimeError, match="no audio"):
        await backend.synthesize("generate nothing")


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_backend_close_clears_client():
    """close() sets _client to None."""
    client = _make_mock_client()
    backend = GoogleTTSBackend(client=client)

    await backend.close()

    assert backend._client is None
