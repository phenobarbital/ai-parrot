"""
Unit tests for Faster Whisper Backend.

Tests for TASK-018 / FEAT-008: MS Teams Voice Note Support.
"""
import sys

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from parrot.integrations.msteams.voice.faster_whisper_backend import (
    FasterWhisperBackend,
)
from parrot.integrations.msteams.voice.models import TranscriptionResult
from parrot.integrations.msteams.voice.backend import AbstractTranscriberBackend


@pytest.fixture
def mock_whisper_model():
    """Mock the WhisperModel class."""
    with patch(
        "faster_whisper.WhisperModel"
    ) as mock:
        # Mock transcribe return value
        mock_info = Mock()
        mock_info.language = "en"
        mock_info.duration = 5.0
        mock_info.language_probability = 0.95

        mock_segment = Mock()
        mock_segment.text = "Hello world"

        mock_instance = MagicMock()
        mock_instance.transcribe.return_value = ([mock_segment], mock_info)
        mock.return_value = mock_instance

        yield mock


@pytest.fixture
def mock_whisper_model_multi_segment():
    """Mock WhisperModel with multiple segments."""
    with patch(
        "faster_whisper.WhisperModel"
    ) as mock:
        mock_info = Mock()
        mock_info.language = "en"
        mock_info.duration = 10.0
        mock_info.language_probability = 0.92

        segment1 = Mock()
        segment1.text = "Hello world."
        segment2 = Mock()
        segment2.text = "How are you today?"
        segment3 = Mock()
        segment3.text = "I hope you are doing well."

        mock_instance = MagicMock()
        mock_instance.transcribe.return_value = (
            [segment1, segment2, segment3],
            mock_info,
        )
        mock.return_value = mock_instance

        yield mock


class TestFasterWhisperBackendInit:
    """Tests for FasterWhisperBackend initialization."""

    def test_initialization_defaults(self):
        """Backend initializes with default config."""
        backend = FasterWhisperBackend()
        assert backend.model_size == "small"
        assert backend.device == "cuda"
        assert backend.compute_type == "float16"
        assert backend._model is None

    def test_initialization_custom(self):
        """Backend initializes with custom config."""
        backend = FasterWhisperBackend(
            model_size="large-v3",
            device="cpu",
            compute_type="int8",
        )
        assert backend.model_size == "large-v3"
        assert backend.device == "cpu"
        assert backend.compute_type == "int8"
        assert backend._model is None

    def test_is_abstract_backend_subclass(self):
        """FasterWhisperBackend extends AbstractTranscriberBackend."""
        backend = FasterWhisperBackend()
        assert isinstance(backend, AbstractTranscriberBackend)

    def test_model_not_loaded_at_init(self):
        """Model is not loaded during initialization (lazy load)."""
        backend = FasterWhisperBackend()
        assert backend._model is None


class TestFasterWhisperBackendTranscribe:
    """Tests for FasterWhisperBackend.transcribe() method."""

    @pytest.mark.asyncio
    async def test_transcribe_loads_model_lazily(self, mock_whisper_model, tmp_path):
        """Transcribe lazily loads model on first call."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        backend = FasterWhisperBackend(device="cpu")
        assert backend._model is None

        await backend.transcribe(audio_file)

        assert mock_whisper_model.called
        assert backend._model is not None

    @pytest.mark.asyncio
    async def test_transcribe_returns_result(self, mock_whisper_model, tmp_path):
        """Transcribe returns TranscriptionResult."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        backend = FasterWhisperBackend(device="cpu")
        result = await backend.transcribe(audio_file)

        assert isinstance(result, TranscriptionResult)
        assert result.text == "Hello world"
        assert result.language == "en"
        assert result.duration_seconds == 5.0
        assert result.confidence == 0.95
        # Processing time can be 0ms with fast mocked execution
        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_transcribe_with_language_hint(self, mock_whisper_model, tmp_path):
        """Transcribe passes language hint to model."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        backend = FasterWhisperBackend(device="cpu")
        await backend.transcribe(audio_file, language="es")

        # Verify language was passed to model
        mock_instance = mock_whisper_model.return_value
        mock_instance.transcribe.assert_called_once()
        call_kwargs = mock_instance.transcribe.call_args[1]
        assert call_kwargs["language"] == "es"

    @pytest.mark.asyncio
    async def test_transcribe_multiple_segments(
        self, mock_whisper_model_multi_segment, tmp_path
    ):
        """Transcribe concatenates multiple segments."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        backend = FasterWhisperBackend(device="cpu")
        result = await backend.transcribe(audio_file)

        assert result.text == "Hello world. How are you today? I hope you are doing well."
        assert result.duration_seconds == 10.0
        assert result.confidence == 0.92

    @pytest.mark.asyncio
    async def test_transcribe_file_not_found(self):
        """Raises FileNotFoundError for missing file."""
        backend = FasterWhisperBackend()

        with pytest.raises(FileNotFoundError) as exc_info:
            await backend.transcribe(Path("/nonexistent/audio.wav"))

        assert "Audio file not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_transcribe_model_reused(self, mock_whisper_model, tmp_path):
        """Model is reused across multiple transcriptions."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        backend = FasterWhisperBackend(device="cpu")

        # First transcription
        await backend.transcribe(audio_file)
        assert mock_whisper_model.call_count == 1

        # Second transcription - model should not be loaded again
        await backend.transcribe(audio_file)
        assert mock_whisper_model.call_count == 1  # Still 1

    @pytest.mark.asyncio
    async def test_transcribe_uses_vad_filter(self, mock_whisper_model, tmp_path):
        """Transcribe enables VAD filter."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        backend = FasterWhisperBackend(device="cpu")
        await backend.transcribe(audio_file)

        mock_instance = mock_whisper_model.return_value
        call_kwargs = mock_instance.transcribe.call_args[1]
        assert call_kwargs["vad_filter"] is True

    @pytest.mark.asyncio
    async def test_transcribe_uses_beam_size(self, mock_whisper_model, tmp_path):
        """Transcribe uses beam_size=5."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        backend = FasterWhisperBackend(device="cpu")
        await backend.transcribe(audio_file)

        mock_instance = mock_whisper_model.return_value
        call_kwargs = mock_instance.transcribe.call_args[1]
        assert call_kwargs["beam_size"] == 5


class TestFasterWhisperBackendClose:
    """Tests for FasterWhisperBackend.close() method."""

    @pytest.mark.asyncio
    async def test_close_releases_model(self, mock_whisper_model, tmp_path):
        """Close releases model memory."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio")

        backend = FasterWhisperBackend(device="cpu")
        await backend.transcribe(audio_file)
        assert backend._model is not None

        await backend.close()
        assert backend._model is None

    @pytest.mark.asyncio
    async def test_close_when_model_not_loaded(self):
        """Close is safe when model was never loaded."""
        backend = FasterWhisperBackend()
        assert backend._model is None

        # Should not raise
        await backend.close()
        assert backend._model is None

    @pytest.mark.asyncio
    async def test_close_clears_cuda_cache(self, mock_whisper_model, tmp_path):
        """Close attempts to clear CUDA cache."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio")

        backend = FasterWhisperBackend(device="cpu")
        await backend.transcribe(audio_file)

        # Patch torch at the import level in builtins
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        with patch.dict("sys.modules", {"torch": mock_torch}):
            await backend.close()
            mock_torch.cuda.empty_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_handles_missing_torch(self, mock_whisper_model, tmp_path):
        """Close handles missing torch gracefully."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio")

        backend = FasterWhisperBackend(device="cpu")
        await backend.transcribe(audio_file)

        # Remove torch from sys.modules to trigger ImportError
        original_torch = sys.modules.get("torch")
        sys.modules["torch"] = None
        try:
            # Should not raise
            await backend.close()
            assert backend._model is None
        finally:
            if original_torch is not None:
                sys.modules["torch"] = original_torch

    @pytest.mark.asyncio
    async def test_model_reloads_after_close(self, mock_whisper_model, tmp_path):
        """Model reloads after close on next transcription."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio")

        backend = FasterWhisperBackend(device="cpu")

        # First transcription
        await backend.transcribe(audio_file)
        assert mock_whisper_model.call_count == 1

        # Close and transcribe again
        await backend.close()
        assert backend._model is None

        await backend.transcribe(audio_file)
        assert mock_whisper_model.call_count == 2


class TestFasterWhisperBackendImports:
    """Tests for import paths."""

    def test_import_from_voice_package(self):
        """Can import from voice package."""
        from parrot.integrations.msteams.voice import FasterWhisperBackend

        assert FasterWhisperBackend is not None

    def test_import_from_backend_module(self):
        """Can import from backend module."""
        from parrot.integrations.msteams.voice.faster_whisper_backend import (
            FasterWhisperBackend,
        )

        assert FasterWhisperBackend is not None

    def test_in_all_exports(self):
        """FasterWhisperBackend is in __all__."""
        from parrot.integrations.msteams import voice

        assert "FasterWhisperBackend" in voice.__all__


class TestFasterWhisperBackendModelConfig:
    """Tests for model configuration."""

    def test_supported_model_sizes(self):
        """Backend accepts various model sizes."""
        sizes = ["tiny", "base", "small", "medium", "large-v3"]
        for size in sizes:
            backend = FasterWhisperBackend(model_size=size)
            assert backend.model_size == size

    def test_supported_devices(self):
        """Backend accepts various device options."""
        devices = ["cuda", "cpu", "auto"]
        for device in devices:
            backend = FasterWhisperBackend(device=device)
            assert backend.device == device

    def test_supported_compute_types(self):
        """Backend accepts various compute types."""
        types = ["float16", "int8", "float32"]
        for compute_type in types:
            backend = FasterWhisperBackend(compute_type=compute_type)
            assert backend.compute_type == compute_type

    @pytest.mark.asyncio
    async def test_model_init_uses_config(self, mock_whisper_model, tmp_path):
        """Model is initialized with configured parameters."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio")

        backend = FasterWhisperBackend(
            model_size="medium",
            device="cpu",
            compute_type="int8",
        )
        await backend.transcribe(audio_file)

        mock_whisper_model.assert_called_once_with(
            "medium",
            device="cpu",
            compute_type="int8",
        )
