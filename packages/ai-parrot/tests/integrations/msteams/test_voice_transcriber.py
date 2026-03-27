"""
Unit tests for Voice Transcriber Service.

Tests for TASK-020 / FEAT-008: MS Teams Voice Note Support.
"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.integrations.msteams.voice.transcriber import VoiceTranscriber
from parrot.integrations.msteams.voice.models import (
    TranscriberBackend,
    TranscriptionResult,
    VoiceTranscriberConfig,
)
from parrot.integrations.msteams.voice.backend import AbstractTranscriberBackend


@pytest.fixture
def config_local():
    """Config for local FasterWhisper backend."""
    return VoiceTranscriberConfig(
        backend=TranscriberBackend.FASTER_WHISPER,
        model_size="tiny",
        max_audio_duration_seconds=60,
    )


@pytest.fixture
def config_openai():
    """Config for OpenAI Whisper backend."""
    return VoiceTranscriberConfig(
        backend=TranscriberBackend.OPENAI_WHISPER,
        openai_api_key="sk-test123",
        max_audio_duration_seconds=60,
    )


@pytest.fixture
def mock_transcription_result():
    """A sample transcription result."""
    return TranscriptionResult(
        text="Hello world",
        language="en",
        duration_seconds=5.0,
        processing_time_ms=500,
    )


class TestVoiceTranscriberInit:
    """Tests for VoiceTranscriber initialization."""

    def test_initialization(self, config_local):
        """Transcriber initializes with config."""
        transcriber = VoiceTranscriber(config_local)
        assert transcriber.config == config_local
        assert transcriber._backend is None

    def test_backend_not_created_at_init(self, config_local):
        """Backend is not created until first use."""
        transcriber = VoiceTranscriber(config_local)
        assert transcriber._backend is None


class TestVoiceTranscriberBackendSelection:
    """Tests for backend selection logic."""

    def test_creates_faster_whisper_backend(self, config_local):
        """Creates FasterWhisperBackend for local config."""
        transcriber = VoiceTranscriber(config_local)
        backend = transcriber._get_backend()
        assert backend.__class__.__name__ == "FasterWhisperBackend"
        assert backend.model_size == "tiny"

    def test_creates_openai_backend(self, config_openai):
        """Creates OpenAIWhisperBackend for cloud config."""
        transcriber = VoiceTranscriber(config_openai)
        backend = transcriber._get_backend()
        assert backend.__class__.__name__ == "OpenAIWhisperBackend"
        assert backend.api_key == "sk-test123"

    def test_openai_requires_api_key(self):
        """Raises ValueError if OpenAI backend but no API key."""
        config = VoiceTranscriberConfig(
            backend=TranscriberBackend.OPENAI_WHISPER,
            openai_api_key=None,
        )
        transcriber = VoiceTranscriber(config)
        with pytest.raises(ValueError, match="API key required"):
            transcriber._get_backend()

    def test_backend_is_reused(self, config_local):
        """Backend is reused on subsequent calls."""
        transcriber = VoiceTranscriber(config_local)
        backend1 = transcriber._get_backend()
        backend2 = transcriber._get_backend()
        assert backend1 is backend2


class TestVoiceTranscriberTranscribeFile:
    """Tests for transcribe_file method."""

    @pytest.mark.asyncio
    async def test_transcribe_file_success(
        self, config_local, mock_transcription_result, tmp_path
    ):
        """Successful file transcription."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        transcriber = VoiceTranscriber(config_local)

        mock_backend = MagicMock(spec=AbstractTranscriberBackend)
        mock_backend.transcribe = AsyncMock(return_value=mock_transcription_result)
        transcriber._backend = mock_backend

        with patch.object(transcriber, "_get_audio_duration", return_value=5.0):
            result = await transcriber.transcribe_file(audio_file)

        assert result.text == "Hello world"
        assert result.language == "en"
        mock_backend.transcribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_transcribe_file_not_found(self, config_local):
        """Raises FileNotFoundError for missing file."""
        transcriber = VoiceTranscriber(config_local)

        with pytest.raises(FileNotFoundError, match="Audio file not found"):
            await transcriber.transcribe_file(Path("/nonexistent/audio.wav"))

    @pytest.mark.asyncio
    async def test_transcribe_file_validates_duration(self, config_local, tmp_path):
        """Rejects audio exceeding duration limit."""
        config_local.max_audio_duration_seconds = 10
        transcriber = VoiceTranscriber(config_local)

        audio_file = tmp_path / "long.wav"
        audio_file.write_bytes(b"fake audio data")

        with patch.object(transcriber, "_get_audio_duration", return_value=120.0):
            with pytest.raises(ValueError, match="exceeds limit"):
                await transcriber.transcribe_file(audio_file)

    @pytest.mark.asyncio
    async def test_transcribe_file_passes_language(
        self, config_local, mock_transcription_result, tmp_path
    ):
        """Language hint is passed to backend."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        transcriber = VoiceTranscriber(config_local)

        mock_backend = MagicMock(spec=AbstractTranscriberBackend)
        mock_backend.transcribe = AsyncMock(return_value=mock_transcription_result)
        transcriber._backend = mock_backend

        with patch.object(transcriber, "_get_audio_duration", return_value=5.0):
            await transcriber.transcribe_file(audio_file, language="es")

        call_kwargs = mock_backend.transcribe.call_args[1]
        assert call_kwargs["language"] == "es"

    @pytest.mark.asyncio
    async def test_transcribe_file_uses_config_language(
        self, mock_transcription_result, tmp_path
    ):
        """Uses config language if not specified."""
        config = VoiceTranscriberConfig(
            backend=TranscriberBackend.FASTER_WHISPER,
            language="fr",
        )
        transcriber = VoiceTranscriber(config)

        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        mock_backend = MagicMock(spec=AbstractTranscriberBackend)
        mock_backend.transcribe = AsyncMock(return_value=mock_transcription_result)
        transcriber._backend = mock_backend

        with patch.object(transcriber, "_get_audio_duration", return_value=5.0):
            await transcriber.transcribe_file(audio_file)

        call_kwargs = mock_backend.transcribe.call_args[1]
        assert call_kwargs["language"] == "fr"


class TestVoiceTranscriberTranscribeUrl:
    """Tests for transcribe_url method."""

    @pytest.mark.asyncio
    async def test_transcribe_url_downloads_and_transcribes(
        self, config_local, mock_transcription_result
    ):
        """Downloads audio from URL and transcribes."""
        transcriber = VoiceTranscriber(config_local)

        mock_temp_path = MagicMock(spec=Path)
        mock_temp_path.exists.return_value = True

        with patch.object(
            transcriber, "_download_audio", new_callable=AsyncMock
        ) as mock_download, patch.object(
            transcriber,
            "transcribe_file",
            new_callable=AsyncMock,
            return_value=mock_transcription_result,
        ):
            mock_download.return_value = mock_temp_path

            result = await transcriber.transcribe_url(
                "https://example.com/audio.ogg"
            )

        assert result.text == "Hello world"
        mock_download.assert_called_once_with(
            "https://example.com/audio.ogg", None
        )

    @pytest.mark.asyncio
    async def test_transcribe_url_passes_auth_token(
        self, config_local, mock_transcription_result
    ):
        """Auth token is passed to download."""
        transcriber = VoiceTranscriber(config_local)

        mock_temp_path = MagicMock(spec=Path)
        mock_temp_path.exists.return_value = True

        with patch.object(
            transcriber, "_download_audio", new_callable=AsyncMock
        ) as mock_download, patch.object(
            transcriber,
            "transcribe_file",
            new_callable=AsyncMock,
            return_value=mock_transcription_result,
        ):
            mock_download.return_value = mock_temp_path

            await transcriber.transcribe_url(
                "https://example.com/audio.ogg",
                auth_token="my-secret-token",
            )

        mock_download.assert_called_once_with(
            "https://example.com/audio.ogg", "my-secret-token"
        )

    @pytest.mark.asyncio
    async def test_transcribe_url_cleans_up_temp_file(
        self, config_local, mock_transcription_result, tmp_path
    ):
        """Cleans up temp file after transcription."""
        transcriber = VoiceTranscriber(config_local)

        # Create a real temp file
        temp_file = tmp_path / "temp_audio.ogg"
        temp_file.write_bytes(b"fake audio data")

        with patch.object(
            transcriber, "_download_audio", new_callable=AsyncMock
        ) as mock_download, patch.object(
            transcriber,
            "transcribe_file",
            new_callable=AsyncMock,
            return_value=mock_transcription_result,
        ):
            mock_download.return_value = temp_file

            await transcriber.transcribe_url("https://example.com/audio.ogg")

        # Temp file should be deleted
        assert not temp_file.exists()

    @pytest.mark.asyncio
    async def test_transcribe_url_cleans_up_on_error(
        self, config_local, tmp_path
    ):
        """Cleans up temp file even if transcription fails."""
        transcriber = VoiceTranscriber(config_local)

        temp_file = tmp_path / "temp_audio.ogg"
        temp_file.write_bytes(b"fake audio data")

        with patch.object(
            transcriber, "_download_audio", new_callable=AsyncMock
        ) as mock_download, patch.object(
            transcriber,
            "transcribe_file",
            new_callable=AsyncMock,
            side_effect=ValueError("Transcription failed"),
        ):
            mock_download.return_value = temp_file

            with pytest.raises(ValueError, match="Transcription failed"):
                await transcriber.transcribe_url("https://example.com/audio.ogg")

        # Temp file should still be deleted
        assert not temp_file.exists()

    @pytest.mark.asyncio
    async def test_transcribe_url_passes_language(
        self, config_local, mock_transcription_result
    ):
        """Language parameter is passed through."""
        transcriber = VoiceTranscriber(config_local)

        mock_temp_path = MagicMock(spec=Path)
        mock_temp_path.exists.return_value = True

        with patch.object(
            transcriber, "_download_audio", new_callable=AsyncMock
        ) as mock_download, patch.object(
            transcriber,
            "transcribe_file",
            new_callable=AsyncMock,
            return_value=mock_transcription_result,
        ) as mock_transcribe:
            mock_download.return_value = mock_temp_path

            await transcriber.transcribe_url(
                "https://example.com/audio.ogg",
                language="de",
            )

        mock_transcribe.assert_called_once_with(mock_temp_path, language="de")


class TestVoiceTranscriberDownload:
    """Tests for audio download functionality."""

    @pytest.mark.asyncio
    async def test_download_audio_success(self, config_local):
        """Successfully downloads audio to temp file."""
        transcriber = VoiceTranscriber(config_local)

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "audio/ogg"}
        mock_response.read = AsyncMock(return_value=b"audio content")

        with patch(
            "parrot.integrations.msteams.voice.transcriber.aiohttp.ClientSession"
        ) as mock_session_cls:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session.get = MagicMock(return_value=AsyncMock())
            mock_session.get.return_value.__aenter__ = AsyncMock(
                return_value=mock_response
            )
            mock_session.get.return_value.__aexit__ = AsyncMock()
            mock_session_cls.return_value = mock_session

            temp_path = await transcriber._download_audio(
                "https://example.com/audio.ogg"
            )

        assert temp_path.exists()
        assert temp_path.suffix == ".ogg"
        content = temp_path.read_bytes()
        assert content == b"audio content"

        # Cleanup
        temp_path.unlink()

    @pytest.mark.asyncio
    async def test_download_audio_with_auth_token(self, config_local):
        """Auth token is included in request headers."""
        transcriber = VoiceTranscriber(config_local)

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "audio/ogg"}
        mock_response.read = AsyncMock(return_value=b"audio content")

        with patch(
            "parrot.integrations.msteams.voice.transcriber.aiohttp.ClientSession"
        ) as mock_session_cls:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_get = MagicMock(return_value=AsyncMock())
            mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_get.return_value.__aexit__ = AsyncMock()
            mock_session.get = mock_get
            mock_session_cls.return_value = mock_session

            temp_path = await transcriber._download_audio(
                "https://example.com/audio.ogg",
                auth_token="secret-token",
            )

            # Verify headers include auth
            call_kwargs = mock_get.call_args[1]
            assert call_kwargs["headers"]["Authorization"] == "Bearer secret-token"

        # Cleanup
        temp_path.unlink()

    @pytest.mark.asyncio
    async def test_download_audio_failure(self, config_local):
        """Raises RuntimeError on download failure."""
        transcriber = VoiceTranscriber(config_local)

        # Create mock response with 404 status
        mock_response = MagicMock()
        mock_response.status = 404

        # Create mock for the response context manager
        mock_response_cm = MagicMock()
        mock_response_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response_cm.__aexit__ = AsyncMock(return_value=None)

        # Create mock session
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response_cm)

        # Create mock for session context manager
        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "parrot.integrations.msteams.voice.transcriber.aiohttp.ClientSession",
            return_value=mock_session_cm,
        ):
            with pytest.raises(RuntimeError, match="Failed to download audio"):
                await transcriber._download_audio("https://example.com/audio.ogg")


class TestVoiceTranscriberContentType:
    """Tests for content type to extension conversion."""

    def test_content_type_ogg(self, config_local):
        """OGG content type returns .ogg."""
        transcriber = VoiceTranscriber(config_local)
        assert transcriber._content_type_to_ext("audio/ogg") == ".ogg"

    def test_content_type_mp3(self, config_local):
        """MP3 content type returns .mp3."""
        transcriber = VoiceTranscriber(config_local)
        assert transcriber._content_type_to_ext("audio/mpeg") == ".mp3"
        assert transcriber._content_type_to_ext("audio/mp3") == ".mp3"

    def test_content_type_wav(self, config_local):
        """WAV content type returns .wav."""
        transcriber = VoiceTranscriber(config_local)
        assert transcriber._content_type_to_ext("audio/wav") == ".wav"
        assert transcriber._content_type_to_ext("audio/x-wav") == ".wav"

    def test_content_type_m4a(self, config_local):
        """M4A content type returns .m4a."""
        transcriber = VoiceTranscriber(config_local)
        assert transcriber._content_type_to_ext("audio/mp4") == ".m4a"
        assert transcriber._content_type_to_ext("audio/m4a") == ".m4a"

    def test_content_type_webm(self, config_local):
        """WebM content type returns .webm."""
        transcriber = VoiceTranscriber(config_local)
        assert transcriber._content_type_to_ext("audio/webm") == ".webm"
        assert transcriber._content_type_to_ext("video/webm") == ".webm"

    def test_content_type_flac(self, config_local):
        """FLAC content type returns .flac."""
        transcriber = VoiceTranscriber(config_local)
        assert transcriber._content_type_to_ext("audio/flac") == ".flac"

    def test_content_type_unknown(self, config_local):
        """Unknown content type defaults to .wav."""
        transcriber = VoiceTranscriber(config_local)
        assert transcriber._content_type_to_ext("application/octet-stream") == ".wav"

    def test_content_type_case_insensitive(self, config_local):
        """Content type matching is case insensitive."""
        transcriber = VoiceTranscriber(config_local)
        assert transcriber._content_type_to_ext("Audio/OGG") == ".ogg"
        assert transcriber._content_type_to_ext("AUDIO/MPEG") == ".mp3"


class TestVoiceTranscriberClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    async def test_close_releases_backend(self, config_local):
        """Close releases backend resources."""
        transcriber = VoiceTranscriber(config_local)

        mock_backend = MagicMock(spec=AbstractTranscriberBackend)
        mock_backend.close = AsyncMock()
        transcriber._backend = mock_backend

        await transcriber.close()

        mock_backend.close.assert_called_once()
        assert transcriber._backend is None

    @pytest.mark.asyncio
    async def test_close_when_no_backend(self, config_local):
        """Close is safe when no backend exists."""
        transcriber = VoiceTranscriber(config_local)
        assert transcriber._backend is None

        # Should not raise
        await transcriber.close()
        assert transcriber._backend is None

    @pytest.mark.asyncio
    async def test_close_can_be_called_multiple_times(self, config_local):
        """Close can be called multiple times safely."""
        transcriber = VoiceTranscriber(config_local)

        mock_backend = MagicMock(spec=AbstractTranscriberBackend)
        mock_backend.close = AsyncMock()
        transcriber._backend = mock_backend

        await transcriber.close()
        await transcriber.close()  # Second call should be safe

        # close() should only be called once
        mock_backend.close.assert_called_once()


class TestVoiceTranscriberImports:
    """Tests for import paths."""

    def test_import_from_voice_package(self):
        """Can import from voice package."""
        from parrot.integrations.msteams.voice import VoiceTranscriber

        assert VoiceTranscriber is not None

    def test_import_from_transcriber_module(self):
        """Can import from transcriber module."""
        from parrot.integrations.msteams.voice.transcriber import VoiceTranscriber

        assert VoiceTranscriber is not None

    def test_in_all_exports(self):
        """VoiceTranscriber is in __all__."""
        from parrot.integrations.msteams import voice

        assert "VoiceTranscriber" in voice.__all__
