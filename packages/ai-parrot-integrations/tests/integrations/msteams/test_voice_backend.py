"""
Unit tests for Abstract Transcriber Backend.

Tests for TASK-017 / FEAT-008: MS Teams Voice Note Support.
"""
import pytest
from pathlib import Path

from parrot.integrations.msteams.voice.backend import AbstractTranscriberBackend
from parrot.integrations.msteams.voice.models import TranscriptionResult


class TestAbstractTranscriberBackend:
    """Tests for AbstractTranscriberBackend ABC."""

    def test_cannot_instantiate_abc(self):
        """ABC cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            AbstractTranscriberBackend()

    def test_concrete_implementation_works(self):
        """Concrete subclass can be instantiated."""

        class MockBackend(AbstractTranscriberBackend):
            async def transcribe(self, audio_path, language=None):
                return TranscriptionResult(
                    text="test",
                    language="en",
                    duration_seconds=1.0,
                    processing_time_ms=100,
                )

        backend = MockBackend()
        assert backend is not None
        assert isinstance(backend, AbstractTranscriberBackend)

    def test_must_implement_transcribe(self):
        """Subclass without transcribe() cannot be instantiated."""

        class IncompleteBackend(AbstractTranscriberBackend):
            pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteBackend()

    @pytest.mark.asyncio
    async def test_close_default_implementation(self):
        """Default close() does nothing and doesn't raise."""

        class MockBackend(AbstractTranscriberBackend):
            async def transcribe(self, audio_path, language=None):
                return TranscriptionResult(
                    text="test",
                    language="en",
                    duration_seconds=1.0,
                    processing_time_ms=100,
                )

        backend = MockBackend()
        # Should not raise any exception
        await backend.close()

    @pytest.mark.asyncio
    async def test_close_can_be_overridden(self):
        """Subclass can override close() method."""
        cleanup_called = False

        class MockBackendWithCleanup(AbstractTranscriberBackend):
            async def transcribe(self, audio_path, language=None):
                return TranscriptionResult(
                    text="test",
                    language="en",
                    duration_seconds=1.0,
                    processing_time_ms=100,
                )

            async def close(self) -> None:
                nonlocal cleanup_called
                cleanup_called = True

        backend = MockBackendWithCleanup()
        await backend.close()
        assert cleanup_called is True

    @pytest.mark.asyncio
    async def test_transcribe_returns_result(self):
        """Transcribe method returns TranscriptionResult."""

        class MockBackend(AbstractTranscriberBackend):
            async def transcribe(self, audio_path, language=None):
                return TranscriptionResult(
                    text="Hello world",
                    language=language or "en",
                    duration_seconds=3.5,
                    processing_time_ms=500,
                    confidence=0.95,
                )

        backend = MockBackend()
        result = await backend.transcribe(Path("/fake/audio.wav"), language="es")

        assert isinstance(result, TranscriptionResult)
        assert result.text == "Hello world"
        assert result.language == "es"
        assert result.duration_seconds == 3.5
        assert result.processing_time_ms == 500
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_transcribe_with_path_object(self):
        """Transcribe accepts Path object."""

        class MockBackend(AbstractTranscriberBackend):
            async def transcribe(self, audio_path, language=None):
                # Verify we received a Path
                assert isinstance(audio_path, Path)
                return TranscriptionResult(
                    text="test",
                    language="en",
                    duration_seconds=1.0,
                    processing_time_ms=100,
                )

        backend = MockBackend()
        audio_path = Path("/path/to/audio.ogg")
        result = await backend.transcribe(audio_path)
        assert result is not None

    @pytest.mark.asyncio
    async def test_transcribe_language_optional(self):
        """Language parameter is optional."""

        class MockBackend(AbstractTranscriberBackend):
            async def transcribe(self, audio_path, language=None):
                return TranscriptionResult(
                    text="test",
                    language="auto-detected",
                    duration_seconds=1.0,
                    processing_time_ms=100,
                )

        backend = MockBackend()
        # Should work without language parameter
        result = await backend.transcribe(Path("/fake/audio.wav"))
        assert result.language == "auto-detected"


class TestAbstractTranscriberBackendImport:
    """Tests for import paths."""

    def test_import_from_voice_package(self):
        """Can import from voice package."""
        from parrot.integrations.msteams.voice import AbstractTranscriberBackend

        assert AbstractTranscriberBackend is not None

    def test_import_from_backend_module(self):
        """Can import from backend module."""
        from parrot.integrations.msteams.voice.backend import (
            AbstractTranscriberBackend,
        )

        assert AbstractTranscriberBackend is not None

    def test_abc_in_all_exports(self):
        """AbstractTranscriberBackend is in __all__."""
        from parrot.integrations.msteams import voice

        assert "AbstractTranscriberBackend" in voice.__all__
