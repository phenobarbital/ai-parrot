"""
Faster Whisper Backend for Voice Transcription.

Local GPU-accelerated transcription backend using the faster-whisper library.
This is the default backend for voice transcription, offering low latency
and no API costs.

Part of FEAT-008: MS Teams Voice Note Support.
"""
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from .backend import AbstractTranscriberBackend
from .models import TranscriptionResult


class FasterWhisperBackend(AbstractTranscriberBackend):
    """
    Local GPU-accelerated transcription using Faster Whisper.

    The model is loaded lazily on first transcription to save GPU memory.
    Call `close()` to release the model when done.

    Args:
        model_size: Whisper model size. Options: "tiny", "base", "small",
            "medium", "large-v3". Larger models are more accurate but slower.
            Default: "small" (good balance of speed and accuracy).
        device: Device to run on. Options: "cuda", "cpu", "auto".
            Default: "cuda" for GPU acceleration.
        compute_type: Precision for computation. Options: "float16", "int8",
            "float32". Default: "float16" for GPU (fastest with good accuracy).

    Example::

        backend = FasterWhisperBackend(model_size="small")
        try:
            result = await backend.transcribe(Path("/path/to/audio.ogg"))
            print(f"Transcription: {result.text}")
        finally:
            await backend.close()  # Release GPU memory
    """

    def __init__(
        self,
        model_size: str = "small",
        device: str = "cuda",
        compute_type: str = "float16",
    ):
        """Initialize the Faster Whisper backend."""
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self.logger = logging.getLogger(__name__)

    def _ensure_model(self) -> None:
        """
        Lazy load the Whisper model.

        The model is only loaded when first needed, saving GPU memory
        at startup. Subsequent calls are no-ops if model is already loaded.
        """
        if self._model is None:
            # Import here to avoid loading CUDA/PyTorch at module import time
            from faster_whisper import WhisperModel

            self.logger.info(
                "Loading Faster Whisper model: %s on %s",
                self.model_size,
                self.device,
            )
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            self.logger.info("Faster Whisper model loaded successfully")

    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio file to text using Faster Whisper.

        Args:
            audio_path: Path to the audio file to transcribe.
                Supported formats: WAV, OGG, MP3, M4A, WebM.
            language: Optional language hint (ISO 639-1 code, e.g., "en", "es").
                If None, the language is auto-detected.

        Returns:
            TranscriptionResult containing the transcribed text, detected
            language, audio duration, confidence score, and processing time.

        Raises:
            FileNotFoundError: If the audio file does not exist.
            RuntimeError: If transcription fails.
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        start_time = time.perf_counter()

        # Run CPU-bound transcription in thread pool to avoid blocking
        result = await asyncio.to_thread(
            self._transcribe_sync, audio_path, language
        )

        processing_time_ms = int((time.perf_counter() - start_time) * 1000)
        result = TranscriptionResult(
            text=result.text,
            language=result.language,
            duration_seconds=result.duration_seconds,
            confidence=result.confidence,
            processing_time_ms=processing_time_ms,
        )

        self.logger.debug(
            "Transcription completed: %d chars in %dms",
            len(result.text),
            processing_time_ms,
        )

        return result

    def _transcribe_sync(
        self,
        audio_path: Path,
        language: Optional[str],
    ) -> TranscriptionResult:
        """
        Synchronous transcription (runs in thread pool).

        This method does the actual transcription work. It's called via
        asyncio.to_thread() to avoid blocking the event loop.
        """
        self._ensure_model()

        self.logger.debug("Starting transcription of: %s", audio_path)

        segments, info = self._model.transcribe(
            str(audio_path),
            language=language,
            beam_size=5,
            vad_filter=True,  # Voice Activity Detection for better accuracy
        )

        # Collect all segments
        text_parts = []
        for segment in segments:
            text_parts.append(segment.text.strip())

        full_text = " ".join(text_parts)

        return TranscriptionResult(
            text=full_text,
            language=info.language,
            duration_seconds=info.duration,
            confidence=info.language_probability,
            processing_time_ms=0,  # Will be overwritten by caller
        )

    async def close(self) -> None:
        """
        Release the model and free GPU memory.

        This method should be called when the backend is no longer needed
        to free up GPU memory. After calling close(), the model will be
        reloaded on the next transcription request.
        """
        if self._model is not None:
            self.logger.info("Releasing Faster Whisper model")
            del self._model
            self._model = None

            # Clear CUDA cache if available
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    self.logger.debug("CUDA cache cleared")
            except ImportError:
                pass  # torch not installed, skip cache clearing
