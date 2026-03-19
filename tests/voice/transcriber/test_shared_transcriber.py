"""Unit tests for the shared voice transcription module (TASK-266).

Verifies that the shared module at `parrot.voice.transcriber` exports
all expected symbols with correct model shapes.
"""
import pytest
from abc import ABC


class TestSharedTranscriberImports:
    """Verify all public imports from the shared location."""

    def test_transcriber_imports_from_shared_location(self):
        """All public symbols importable from parrot.voice.transcriber."""
        from parrot.voice.transcriber import (
            VoiceTranscriber,
            VoiceTranscriberConfig,
            TranscriptionResult,
            TranscriberBackend,
            AbstractTranscriberBackend,
            FasterWhisperBackend,
            OpenAIWhisperBackend,
        )
        assert VoiceTranscriber is not None
        assert VoiceTranscriberConfig is not None
        assert TranscriptionResult is not None
        assert TranscriberBackend is not None
        assert AbstractTranscriberBackend is not None
        assert FasterWhisperBackend is not None
        assert OpenAIWhisperBackend is not None

    def test_all_exports_list(self):
        """__all__ contains all expected symbols."""
        from parrot.voice.transcriber import __all__

        expected = {
            "VoiceTranscriber",
            "AbstractTranscriberBackend",
            "FasterWhisperBackend",
            "OpenAIWhisperBackend",
            "TranscriberBackend",
            "VoiceTranscriberConfig",
            "TranscriptionResult",
        }
        assert set(__all__) == expected


class TestVoiceTranscriberConfig:
    """Verify VoiceTranscriberConfig model fields match original."""

    def test_config_model_fields(self):
        """VoiceTranscriberConfig has all expected fields."""
        from parrot.voice.transcriber import VoiceTranscriberConfig

        expected_fields = {
            "enabled", "backend", "model_size", "language",
            "show_transcription", "max_audio_duration_seconds",
            "openai_api_key",
        }
        assert set(VoiceTranscriberConfig.model_fields.keys()) == expected_fields

    def test_config_defaults(self):
        """VoiceTranscriberConfig defaults are correct."""
        from parrot.voice.transcriber import VoiceTranscriberConfig

        config = VoiceTranscriberConfig()
        assert config.enabled is True
        assert config.backend.value == "faster_whisper"
        assert config.model_size == "small"
        assert config.language is None
        assert config.show_transcription is True
        assert config.max_audio_duration_seconds == 60
        assert config.openai_api_key is None

    def test_config_custom_values(self):
        """VoiceTranscriberConfig accepts custom values."""
        from parrot.voice.transcriber import VoiceTranscriberConfig, TranscriberBackend

        config = VoiceTranscriberConfig(
            enabled=False,
            backend=TranscriberBackend.OPENAI_WHISPER,
            model_size="large-v3",
            language="es",
            show_transcription=False,
            max_audio_duration_seconds=120,
            openai_api_key="sk-test",
        )
        assert config.enabled is False
        assert config.backend == TranscriberBackend.OPENAI_WHISPER
        assert config.model_size == "large-v3"
        assert config.language == "es"
        assert config.show_transcription is False
        assert config.max_audio_duration_seconds == 120
        assert config.openai_api_key == "sk-test"


class TestTranscriptionResult:
    """Verify TranscriptionResult model fields."""

    def test_transcription_result_fields(self):
        """TranscriptionResult has all expected fields."""
        from parrot.voice.transcriber import TranscriptionResult

        expected_fields = {
            "text", "language", "duration_seconds",
            "confidence", "processing_time_ms",
        }
        assert set(TranscriptionResult.model_fields.keys()) == expected_fields

    def test_transcription_result_creation(self):
        """TranscriptionResult can be created with valid data."""
        from parrot.voice.transcriber import TranscriptionResult

        result = TranscriptionResult(
            text="Hello world",
            language="en",
            duration_seconds=2.5,
            confidence=0.95,
            processing_time_ms=500,
        )
        assert result.text == "Hello world"
        assert result.language == "en"
        assert result.duration_seconds == 2.5
        assert result.confidence == 0.95
        assert result.processing_time_ms == 500

    def test_transcription_result_optional_confidence(self):
        """TranscriptionResult confidence is optional."""
        from parrot.voice.transcriber import TranscriptionResult

        result = TranscriptionResult(
            text="Test",
            language="en",
            duration_seconds=1.0,
            processing_time_ms=100,
        )
        assert result.confidence is None


class TestTranscriberBackend:
    """Verify TranscriberBackend enum."""

    def test_transcriber_backend_values(self):
        """TranscriberBackend has expected values."""
        from parrot.voice.transcriber import TranscriberBackend

        assert TranscriberBackend.FASTER_WHISPER.value == "faster_whisper"
        assert TranscriberBackend.OPENAI_WHISPER.value == "openai_whisper"

    def test_transcriber_backend_is_str_enum(self):
        """TranscriberBackend is a string enum."""
        from parrot.voice.transcriber import TranscriberBackend

        assert isinstance(TranscriberBackend.FASTER_WHISPER, str)
        assert TranscriberBackend.FASTER_WHISPER == "faster_whisper"


class TestAbstractTranscriberBackend:
    """Verify AbstractTranscriberBackend interface."""

    def test_abstract_backend_is_abc(self):
        """AbstractTranscriberBackend is an abstract class."""
        from parrot.voice.transcriber import AbstractTranscriberBackend

        assert issubclass(AbstractTranscriberBackend, ABC)

    def test_abstract_backend_has_transcribe_method(self):
        """AbstractTranscriberBackend defines transcribe method."""
        from parrot.voice.transcriber import AbstractTranscriberBackend

        assert hasattr(AbstractTranscriberBackend, "transcribe")

    def test_abstract_backend_has_close_method(self):
        """AbstractTranscriberBackend defines close method."""
        from parrot.voice.transcriber import AbstractTranscriberBackend

        assert hasattr(AbstractTranscriberBackend, "close")

    def test_cannot_instantiate_abstract_backend(self):
        """AbstractTranscriberBackend cannot be instantiated directly."""
        from parrot.voice.transcriber import AbstractTranscriberBackend

        with pytest.raises(TypeError):
            AbstractTranscriberBackend()
