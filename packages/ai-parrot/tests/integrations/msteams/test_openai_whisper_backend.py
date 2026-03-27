"""
Unit tests for OpenAI Whisper Backend.

Tests for TASK-019 / FEAT-008: MS Teams Voice Note Support.
"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from parrot.integrations.msteams.voice.openai_backend import OpenAIWhisperBackend
from parrot.integrations.msteams.voice.models import TranscriptionResult
from parrot.integrations.msteams.voice.backend import AbstractTranscriberBackend


class TestOpenAIWhisperBackendInit:
    """Tests for OpenAIWhisperBackend initialization."""

    def test_requires_api_key(self):
        """Raises ValueError if API key is empty."""
        with pytest.raises(ValueError, match="API key is required"):
            OpenAIWhisperBackend(api_key="")

    def test_requires_api_key_none(self):
        """Raises ValueError if API key is None."""
        with pytest.raises(ValueError, match="API key is required"):
            OpenAIWhisperBackend(api_key=None)

    def test_initialization_with_key(self):
        """Backend initializes with API key."""
        backend = OpenAIWhisperBackend(api_key="sk-test123")
        assert backend.api_key == "sk-test123"
        assert backend.model == "whisper-1"
        assert backend.max_retries == 3
        assert backend._session is None

    def test_initialization_custom_config(self):
        """Backend initializes with custom config."""
        backend = OpenAIWhisperBackend(
            api_key="sk-test",
            model="whisper-2",
            max_retries=5,
            timeout_seconds=120,
        )
        assert backend.model == "whisper-2"
        assert backend.max_retries == 5
        assert backend.timeout.total == 120

    def test_is_abstract_backend_subclass(self):
        """OpenAIWhisperBackend extends AbstractTranscriberBackend."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        assert isinstance(backend, AbstractTranscriberBackend)


class TestOpenAIWhisperBackendTranscribe:
    """Tests for OpenAIWhisperBackend.transcribe() method."""

    @pytest.fixture
    def mock_successful_response(self):
        """Create a mock successful API response."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "text": "Hello world",
                "language": "en",
                "duration": 5.0,
            }
        )
        return mock_response

    @pytest.mark.asyncio
    async def test_transcribe_success(self, tmp_path, mock_successful_response):
        """Successful transcription returns TranscriptionResult."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=AsyncMock())
        mock_session.post.return_value.__aenter__.return_value = (
            mock_successful_response
        )

        backend = OpenAIWhisperBackend(api_key="sk-test")
        backend._session = mock_session

        result = await backend.transcribe(audio_file)

        assert isinstance(result, TranscriptionResult)
        assert result.text == "Hello world"
        assert result.language == "en"
        assert result.duration_seconds == 5.0
        assert result.confidence is None  # OpenAI doesn't return confidence
        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_transcribe_with_language(self, tmp_path, mock_successful_response):
        """Transcribe passes language parameter to API."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=AsyncMock())
        mock_session.post.return_value.__aenter__.return_value = (
            mock_successful_response
        )

        backend = OpenAIWhisperBackend(api_key="sk-test")
        backend._session = mock_session

        await backend.transcribe(audio_file, language="es")

        # Verify post was called
        mock_session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_transcribe_file_not_found(self):
        """Raises FileNotFoundError for missing file."""
        backend = OpenAIWhisperBackend(api_key="sk-test")

        with pytest.raises(FileNotFoundError, match="Audio file not found"):
            await backend.transcribe(Path("/nonexistent/audio.wav"))

    @pytest.mark.asyncio
    async def test_transcribe_auth_error(self, tmp_path):
        """Raises RuntimeError on authentication failure."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.text = AsyncMock(return_value="Unauthorized")
        mock_response.request_info = MagicMock()
        mock_response.history = []

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=AsyncMock())
        mock_session.post.return_value.__aenter__.return_value = mock_response

        backend = OpenAIWhisperBackend(api_key="sk-invalid")
        backend._session = mock_session

        with pytest.raises(RuntimeError, match="authentication failed"):
            await backend.transcribe(audio_file)

    @pytest.mark.asyncio
    async def test_transcribe_rate_limit_retry(self, tmp_path, mock_successful_response):
        """Retries on rate limit (429) with backoff."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        # First response: rate limited, second: success
        mock_rate_limited = AsyncMock()
        mock_rate_limited.status = 429
        mock_rate_limited.text = AsyncMock(return_value="Rate limited")
        mock_rate_limited.request_info = MagicMock()
        mock_rate_limited.history = []

        call_count = 0

        async def mock_context_manager(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_rate_limited
            return mock_successful_response

        mock_session = MagicMock()
        mock_session.closed = False
        mock_post = MagicMock(return_value=AsyncMock())
        mock_post.return_value.__aenter__ = mock_context_manager
        mock_session.post = mock_post

        backend = OpenAIWhisperBackend(api_key="sk-test", max_retries=3)
        backend._session = mock_session

        # Patch sleep to avoid waiting
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await backend.transcribe(audio_file)

        assert result.text == "Hello world"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_transcribe_max_retries_exceeded(self, tmp_path):
        """Raises RuntimeError after max retries exceeded."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        mock_response = AsyncMock()
        mock_response.status = 429
        mock_response.text = AsyncMock(return_value="Rate limited")
        mock_response.request_info = MagicMock()
        mock_response.history = []

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=AsyncMock())
        mock_session.post.return_value.__aenter__.return_value = mock_response

        backend = OpenAIWhisperBackend(api_key="sk-test", max_retries=2)
        backend._session = mock_session

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="failed after 2 attempts"):
                await backend.transcribe(audio_file)

    @pytest.mark.asyncio
    async def test_transcribe_server_error(self, tmp_path):
        """Raises RuntimeError on server error (5xx)."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")
        mock_response.request_info = MagicMock()
        mock_response.history = []

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.post = MagicMock(return_value=AsyncMock())
        mock_session.post.return_value.__aenter__.return_value = mock_response

        backend = OpenAIWhisperBackend(api_key="sk-test")
        backend._session = mock_session

        with pytest.raises(RuntimeError, match="OpenAI API error"):
            await backend.transcribe(audio_file)


class TestOpenAIWhisperBackendContentType:
    """Tests for content type detection."""

    def test_content_type_wav(self):
        """WAV files get correct content type."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        assert backend._get_content_type(Path("audio.wav")) == "audio/wav"

    def test_content_type_mp3(self):
        """MP3 files get correct content type."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        assert backend._get_content_type(Path("audio.mp3")) == "audio/mpeg"

    def test_content_type_ogg(self):
        """OGG files get correct content type."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        assert backend._get_content_type(Path("audio.ogg")) == "audio/ogg"

    def test_content_type_m4a(self):
        """M4A files get correct content type."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        assert backend._get_content_type(Path("audio.m4a")) == "audio/m4a"

    def test_content_type_webm(self):
        """WebM files get correct content type."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        assert backend._get_content_type(Path("audio.webm")) == "audio/webm"

    def test_content_type_flac(self):
        """FLAC files get correct content type."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        assert backend._get_content_type(Path("audio.flac")) == "audio/flac"

    def test_content_type_unknown_fallback(self):
        """Unknown extensions fallback to audio/wav."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        assert backend._get_content_type(Path("audio.xyz")) == "audio/wav"

    def test_content_type_case_insensitive(self):
        """Content type detection is case insensitive."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        assert backend._get_content_type(Path("audio.WAV")) == "audio/wav"
        assert backend._get_content_type(Path("audio.MP3")) == "audio/mpeg"


class TestOpenAIWhisperBackendClose:
    """Tests for OpenAIWhisperBackend.close() method."""

    @pytest.mark.asyncio
    async def test_close_session(self):
        """Close properly closes aiohttp session."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        backend._session = mock_session

        await backend.close()

        mock_session.close.assert_called_once()
        assert backend._session is None

    @pytest.mark.asyncio
    async def test_close_when_no_session(self):
        """Close is safe when no session exists."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        assert backend._session is None

        # Should not raise
        await backend.close()
        assert backend._session is None

    @pytest.mark.asyncio
    async def test_close_when_session_already_closed(self):
        """Close is safe when session is already closed."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        mock_session = MagicMock()
        mock_session.closed = True  # Already closed
        mock_session.close = AsyncMock()
        backend._session = mock_session

        # Should not attempt to close again
        await backend.close()
        mock_session.close.assert_not_called()


class TestOpenAIWhisperBackendSession:
    """Tests for session management."""

    @pytest.mark.asyncio
    async def test_get_session_creates_new(self):
        """_get_session creates a new session if none exists."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        assert backend._session is None

        with patch.object(
            aiohttp, "ClientSession", return_value=MagicMock()
        ) as mock_cls:
            session = await backend._get_session()
            mock_cls.assert_called_once()
            assert session is not None

    @pytest.mark.asyncio
    async def test_get_session_reuses_existing(self):
        """_get_session reuses existing session."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        mock_session = MagicMock()
        mock_session.closed = False
        backend._session = mock_session

        session = await backend._get_session()

        assert session is mock_session

    @pytest.mark.asyncio
    async def test_get_session_recreates_if_closed(self):
        """_get_session creates new session if existing is closed."""
        backend = OpenAIWhisperBackend(api_key="sk-test")
        mock_closed_session = MagicMock()
        mock_closed_session.closed = True
        backend._session = mock_closed_session

        with patch.object(
            aiohttp, "ClientSession", return_value=MagicMock()
        ) as mock_cls:
            session = await backend._get_session()
            mock_cls.assert_called_once()
            assert session is not mock_closed_session


class TestOpenAIWhisperBackendImports:
    """Tests for import paths."""

    def test_import_from_voice_package(self):
        """Can import from voice package."""
        from parrot.integrations.msteams.voice import OpenAIWhisperBackend

        assert OpenAIWhisperBackend is not None

    def test_import_from_openai_module(self):
        """Can import from openai_backend module."""
        from parrot.integrations.msteams.voice.openai_backend import (
            OpenAIWhisperBackend,
        )

        assert OpenAIWhisperBackend is not None

    def test_in_all_exports(self):
        """OpenAIWhisperBackend is in __all__."""
        from parrot.integrations.msteams import voice

        assert "OpenAIWhisperBackend" in voice.__all__


class TestOpenAIWhisperBackendAPIURL:
    """Tests for API URL configuration."""

    def test_api_url_is_correct(self):
        """API URL points to OpenAI transcription endpoint."""
        assert (
            OpenAIWhisperBackend.API_URL
            == "https://api.openai.com/v1/audio/transcriptions"
        )
