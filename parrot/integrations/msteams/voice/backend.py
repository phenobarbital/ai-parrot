"""
Abstract Transcriber Backend.

Defines the abstract base class for voice transcription backends.
Both FasterWhisperBackend and OpenAIWhisperBackend implement this interface,
allowing the VoiceTranscriber service to work with either backend interchangeably.

Part of FEAT-008: MS Teams Voice Note Support.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from .models import TranscriptionResult


class AbstractTranscriberBackend(ABC):
    """
    Abstract base class for transcription backends.

    This defines the interface that all transcription backends must implement.
    The `transcribe` method is abstract and must be implemented by subclasses.
    The `close` method has a default no-op implementation.

    Example usage::

        class MyBackend(AbstractTranscriberBackend):
            async def transcribe(self, audio_path, language=None):
                # Implementation here
                return TranscriptionResult(...)

        backend = MyBackend()
        result = await backend.transcribe(Path("/path/to/audio.wav"))
        await backend.close()
    """

    @abstractmethod
    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio file to text.

        This is the core method that converts speech in an audio file
        to text. Implementations should handle various audio formats
        and return structured results with metadata.

        Args:
            audio_path: Path to the audio file to transcribe.
                Supported formats depend on the backend implementation,
                but typically include WAV, OGG, MP3, M4A, and WebM.
            language: Optional language hint (ISO 639-1 code, e.g., "en", "es").
                If None, the backend should attempt to auto-detect the language.

        Returns:
            TranscriptionResult containing:
                - text: The transcribed text
                - language: Detected or specified language code
                - duration_seconds: Audio duration
                - confidence: Optional confidence score (0.0 to 1.0)
                - processing_time_ms: Time taken to transcribe

        Raises:
            FileNotFoundError: If audio_path does not exist.
            ValueError: If the audio format is unsupported by this backend.
            RuntimeError: If transcription fails due to backend errors.

        Example::

            result = await backend.transcribe(
                Path("/path/to/audio.ogg"),
                language="en"
            )
            print(f"Transcribed: {result.text}")
        """
        ...

    async def close(self) -> None:
        """
        Release resources held by the backend.

        This method should be called when the backend is no longer needed
        to free up resources such as loaded models, network connections,
        or GPU memory.

        The default implementation does nothing. Subclasses should override
        this method if they hold resources that need explicit cleanup.

        Example::

            backend = FasterWhisperBackend()
            try:
                result = await backend.transcribe(audio_path)
            finally:
                await backend.close()  # Release GPU memory
        """
        pass
