"""
Unit tests for Voice Transcription Data Models.

Tests for TASK-016 / FEAT-008: MS Teams Voice Note Support.
"""
import pytest
from pydantic import ValidationError

from parrot.integrations.msteams.voice.models import (
    AudioAttachment,
    TranscriberBackend,
    TranscriptionResult,
    VoiceTranscriberConfig,
)


class TestTranscriberBackend:
    """Tests for TranscriberBackend enum."""

    def test_enum_values(self):
        """Enum has expected values."""
        assert TranscriberBackend.FASTER_WHISPER.value == "faster_whisper"
        assert TranscriberBackend.OPENAI_WHISPER.value == "openai_whisper"

    def test_enum_is_string(self):
        """Enum values are strings for JSON serialization."""
        assert isinstance(TranscriberBackend.FASTER_WHISPER, str)
        assert TranscriberBackend.FASTER_WHISPER.value == "faster_whisper"

    def test_enum_from_string(self):
        """Enum can be created from string value."""
        backend = TranscriberBackend("faster_whisper")
        assert backend == TranscriberBackend.FASTER_WHISPER


class TestVoiceTranscriberConfig:
    """Tests for VoiceTranscriberConfig model."""

    def test_default_values(self):
        """Config has sensible defaults."""
        config = VoiceTranscriberConfig()
        assert config.enabled is True
        assert config.backend == TranscriberBackend.FASTER_WHISPER
        assert config.model_size == "small"
        assert config.language is None
        assert config.show_transcription is True
        assert config.max_audio_duration_seconds == 60
        assert config.openai_api_key is None

    def test_custom_values(self):
        """Config accepts custom values."""
        config = VoiceTranscriberConfig(
            enabled=False,
            backend=TranscriberBackend.OPENAI_WHISPER,
            model_size="large-v3",
            language="es",
            show_transcription=False,
            max_audio_duration_seconds=120,
            openai_api_key="sk-test123",
        )
        assert config.enabled is False
        assert config.backend == TranscriberBackend.OPENAI_WHISPER
        assert config.model_size == "large-v3"
        assert config.language == "es"
        assert config.show_transcription is False
        assert config.max_audio_duration_seconds == 120
        assert config.openai_api_key == "sk-test123"

    def test_openai_backend_accepts_key(self):
        """OpenAI backend should accept api_key."""
        config = VoiceTranscriberConfig(
            backend=TranscriberBackend.OPENAI_WHISPER,
            openai_api_key="sk-test123"
        )
        assert config.openai_api_key == "sk-test123"

    def test_duration_validation_min(self):
        """Duration must be at least 1 second."""
        with pytest.raises(ValidationError) as exc_info:
            VoiceTranscriberConfig(max_audio_duration_seconds=0)
        assert "max_audio_duration_seconds" in str(exc_info.value)

    def test_duration_validation_max(self):
        """Duration must be at most 300 seconds."""
        with pytest.raises(ValidationError) as exc_info:
            VoiceTranscriberConfig(max_audio_duration_seconds=500)
        assert "max_audio_duration_seconds" in str(exc_info.value)

    def test_json_serialization(self):
        """Config serializes to JSON correctly."""
        config = VoiceTranscriberConfig(
            backend=TranscriberBackend.FASTER_WHISPER,
            model_size="medium",
        )
        json_data = config.model_dump_json()
        assert "faster_whisper" in json_data
        assert "medium" in json_data

    def test_json_deserialization(self):
        """Config deserializes from JSON correctly."""
        json_str = '{"enabled": true, "backend": "openai_whisper", "model_size": "tiny"}'
        config = VoiceTranscriberConfig.model_validate_json(json_str)
        assert config.backend == TranscriberBackend.OPENAI_WHISPER
        assert config.model_size == "tiny"


class TestTranscriptionResult:
    """Tests for TranscriptionResult model."""

    def test_required_fields(self):
        """Result requires text, language, duration, processing_time."""
        result = TranscriptionResult(
            text="Hello world",
            language="en",
            duration_seconds=5.2,
            processing_time_ms=1200
        )
        assert result.text == "Hello world"
        assert result.language == "en"
        assert result.duration_seconds == 5.2
        assert result.processing_time_ms == 1200
        assert result.confidence is None  # optional

    def test_with_confidence(self):
        """Result accepts optional confidence score."""
        result = TranscriptionResult(
            text="Test",
            language="en",
            duration_seconds=1.0,
            processing_time_ms=100,
            confidence=0.95
        )
        assert result.confidence == 0.95

    def test_confidence_validation(self):
        """Confidence must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            TranscriptionResult(
                text="Test",
                language="en",
                duration_seconds=1.0,
                processing_time_ms=100,
                confidence=1.5  # invalid
            )

    def test_duration_non_negative(self):
        """Duration cannot be negative."""
        with pytest.raises(ValidationError):
            TranscriptionResult(
                text="Test",
                language="en",
                duration_seconds=-1.0,
                processing_time_ms=100
            )

    def test_processing_time_non_negative(self):
        """Processing time cannot be negative."""
        with pytest.raises(ValidationError):
            TranscriptionResult(
                text="Test",
                language="en",
                duration_seconds=1.0,
                processing_time_ms=-100
            )

    def test_json_serialization(self):
        """Result serializes to JSON correctly."""
        result = TranscriptionResult(
            text="Hello world",
            language="en",
            duration_seconds=3.5,
            processing_time_ms=850,
            confidence=0.95
        )
        json_data = result.model_dump()
        assert json_data["text"] == "Hello world"
        assert json_data["language"] == "en"
        assert json_data["duration_seconds"] == 3.5
        assert json_data["processing_time_ms"] == 850
        assert json_data["confidence"] == 0.95


class TestAudioAttachment:
    """Tests for AudioAttachment model."""

    def test_required_fields(self):
        """Attachment requires content_url and content_type."""
        attachment = AudioAttachment(
            content_url="https://teams.microsoft.com/files/audio.ogg",
            content_type="audio/ogg"
        )
        assert attachment.content_url == "https://teams.microsoft.com/files/audio.ogg"
        assert attachment.content_type == "audio/ogg"
        assert attachment.name is None
        assert attachment.size_bytes is None

    def test_with_optional_fields(self):
        """Attachment accepts optional fields."""
        attachment = AudioAttachment(
            content_url="https://teams.microsoft.com/files/audio.ogg",
            content_type="audio/ogg",
            name="voice_note.ogg",
            size_bytes=24576
        )
        assert attachment.name == "voice_note.ogg"
        assert attachment.size_bytes == 24576

    def test_is_voice_note_ogg(self):
        """OGG audio is recognized as voice note."""
        attachment = AudioAttachment(
            content_url="https://example.com/audio.ogg",
            content_type="audio/ogg"
        )
        assert attachment.is_voice_note is True

    def test_is_voice_note_mp3(self):
        """MP3 audio is recognized as voice note."""
        attachment = AudioAttachment(
            content_url="https://example.com/audio.mp3",
            content_type="audio/mpeg"
        )
        assert attachment.is_voice_note is True

    def test_is_voice_note_wav(self):
        """WAV audio is recognized as voice note."""
        attachment = AudioAttachment(
            content_url="https://example.com/audio.wav",
            content_type="audio/wav"
        )
        assert attachment.is_voice_note is True

    def test_is_voice_note_webm(self):
        """WebM audio is recognized as voice note."""
        attachment = AudioAttachment(
            content_url="https://example.com/audio.webm",
            content_type="audio/webm"
        )
        assert attachment.is_voice_note is True

    def test_is_voice_note_video_webm(self):
        """Video WebM (with audio) is recognized as voice note."""
        attachment = AudioAttachment(
            content_url="https://example.com/video.webm",
            content_type="video/webm"
        )
        assert attachment.is_voice_note is True

    def test_is_voice_note_unsupported(self):
        """Non-audio types are not voice notes."""
        attachment = AudioAttachment(
            content_url="https://example.com/image.png",
            content_type="image/png"
        )
        assert attachment.is_voice_note is False

    def test_file_extension_ogg(self):
        """OGG content type returns .ogg extension."""
        attachment = AudioAttachment(
            content_url="https://example.com/audio",
            content_type="audio/ogg"
        )
        assert attachment.file_extension == ".ogg"

    def test_file_extension_mp3(self):
        """MPEG content type returns .mp3 extension."""
        attachment = AudioAttachment(
            content_url="https://example.com/audio",
            content_type="audio/mpeg"
        )
        assert attachment.file_extension == ".mp3"

    def test_file_extension_wav(self):
        """WAV content type returns .wav extension."""
        attachment = AudioAttachment(
            content_url="https://example.com/audio",
            content_type="audio/wav"
        )
        assert attachment.file_extension == ".wav"

    def test_file_extension_fallback(self):
        """Unknown content type returns .wav as fallback."""
        attachment = AudioAttachment(
            content_url="https://example.com/audio",
            content_type="application/octet-stream"
        )
        assert attachment.file_extension == ".wav"

    def test_size_non_negative(self):
        """Size cannot be negative."""
        with pytest.raises(ValidationError):
            AudioAttachment(
                content_url="https://example.com/audio.ogg",
                content_type="audio/ogg",
                size_bytes=-100
            )

    def test_json_serialization(self):
        """Attachment serializes to JSON correctly."""
        attachment = AudioAttachment(
            content_url="https://teams.microsoft.com/files/audio.ogg",
            content_type="audio/ogg",
            name="voice_note.ogg",
            size_bytes=24576
        )
        json_data = attachment.model_dump()
        assert json_data["content_url"] == "https://teams.microsoft.com/files/audio.ogg"
        assert json_data["content_type"] == "audio/ogg"
        assert json_data["name"] == "voice_note.ogg"
        assert json_data["size_bytes"] == 24576
