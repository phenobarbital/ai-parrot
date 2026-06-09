"""
Moonshine STT Backend.

Opt-in sub-second speech-to-text backend built on the Moonshine ONNX models.
Implements :class:`AbstractTranscriberBackend` so the :class:`VoiceTranscriber`
service can select it interchangeably with the default FasterWhisper backend.

Mirrors the structure of :class:`FasterWhisperBackend`: the model is loaded
lazily on first transcription and the CPU/GPU-bound inference runs off the
event loop via ``asyncio.to_thread``.

Opt-in only — FasterWhisper remains the default STT backend
(``VoiceTranscriberConfig.backend == TranscriberBackend.FASTER_WHISPER``).
The Moonshine runtime ships behind the
``ai-parrot-integrations[voice-moonshine]`` extra; when it is missing the
backend raises ``ImportError`` / ``RuntimeError``.

Added by FEAT-231 (AgentTalk Voice Support).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import wave
from pathlib import Path
from typing import Optional, Tuple

from .backend import AbstractTranscriberBackend
from .models import TranscriptionResult

# Default Moonshine model. ``moonshine/base`` balances speed and accuracy;
# ``moonshine/tiny`` is faster/smaller. Both are English-only.
_DEFAULT_MODEL = "moonshine/base"


class MoonshineSTTBackend(AbstractTranscriberBackend):
    """
    Sub-second speech-to-text backend using the Moonshine ONNX models.

    The model is loaded lazily on first ``transcribe`` call to keep
    construction cheap (so ``VoiceTranscriber._get_backend`` can build the
    backend without paying the model-load cost). Inference runs in a worker
    thread via ``asyncio.to_thread`` so the event loop is never blocked.

    Args:
        model_name: Moonshine model identifier (``"moonshine/base"`` default
            or ``"moonshine/tiny"``).
        **kwargs: Extra keyword arguments are accepted and ignored to allow
            forward-compatible construction.

    Example::

        backend = MoonshineSTTBackend(model_name="moonshine/base")
        try:
            result = await backend.transcribe(Path("/path/to/audio.wav"))
            print(result.text)
        finally:
            await backend.close()
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL, **kwargs) -> None:
        """Initialize the Moonshine backend (no model load here)."""
        self.model_name = model_name
        self.logger = logging.getLogger(__name__)
        # Lazily-imported Moonshine transcribe callable (see ``_ensure_model``).
        self._transcribe_fn = None

    def _ensure_model(self) -> None:
        """
        Lazily import the Moonshine runtime.

        Imports the Moonshine package only when first needed so server boot
        and backend construction never require the heavy dependency.

        Raises:
            ImportError: If the Moonshine runtime (the ``voice-moonshine``
                extra) is not installed.
        """
        if self._transcribe_fn is not None:
            return
        # The Moonshine runtime ships under two distribution/import names:
        # ``useful-moonshine-onnx`` (import ``moonshine_onnx``) and
        # ``useful-moonshine`` (import ``moonshine``). Accept either.
        moonshine_mod = None
        for module_name in ("moonshine_onnx", "moonshine"):
            try:
                moonshine_mod = __import__(module_name)
                break
            except ImportError:
                continue
        if moonshine_mod is None:  # pragma: no cover - exercised via stub
            raise ImportError(
                "Moonshine STT backend requires the Moonshine runtime. "
                "Install the extra: "
                "pip install 'ai-parrot-integrations[voice-moonshine]'."
            )
        self.logger.info(
            "MoonshineSTTBackend: using Moonshine model '%s'", self.model_name
        )
        self._transcribe_fn = moonshine_mod.transcribe

    async def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe an audio file to text using Moonshine.

        Args:
            audio_path: Path to the audio file to transcribe.
            language: Optional language hint. Moonshine base/tiny models are
                English-only; the hint is recorded but not used to switch
                models. ``None`` defaults the recorded language to ``"en"``.

        Returns:
            ``TranscriptionResult`` with the transcribed text, language,
            audio duration, and processing time.

        Raises:
            FileNotFoundError: If ``audio_path`` does not exist.
            ImportError: If the ``voice-moonshine`` extra is not installed.
            RuntimeError: If transcription fails.
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        if language and language.lower() not in ("en", "en-us", "en-gb"):
            self.logger.warning(
                "MoonshineSTTBackend: models are English-only; language=%r "
                "hint is ignored.",
                language,
            )

        start_time = time.perf_counter()

        # Run CPU/GPU-bound inference in a worker thread (mirror FasterWhisper).
        text, detected_language = await asyncio.to_thread(
            self._transcribe_sync, audio_path, language
        )

        processing_time_ms = int((time.perf_counter() - start_time) * 1000)
        duration_seconds = self._probe_duration(audio_path)

        result = TranscriptionResult(
            text=text,
            language=detected_language or "en",
            duration_seconds=duration_seconds,
            confidence=None,
            processing_time_ms=processing_time_ms,
        )

        self.logger.debug(
            "MoonshineSTTBackend: transcribed %d chars in %dms",
            len(result.text),
            processing_time_ms,
        )
        return result

    def _transcribe_sync(
        self,
        audio_path: Path,
        language: Optional[str],
    ) -> Tuple[str, Optional[str]]:
        """
        Synchronous Moonshine inference (runs in a worker thread).

        Loads the Moonshine runtime lazily, runs inference, and returns the
        transcribed text plus the (English) language. Isolated so unit tests
        can stub it without touching the Moonshine runtime.

        Args:
            audio_path: Path to the audio file.
            language: Optional BCP-47/ISO 639-1 language hint.

        Returns:
            Tuple of ``(text, language)``.
        """
        self._ensure_model()
        self.logger.debug("MoonshineSTTBackend: transcribing %s", audio_path)
        # ``moonshine.transcribe`` returns a list of decoded strings.
        output = self._transcribe_fn(str(audio_path), self.model_name)
        if isinstance(output, (list, tuple)):
            text = " ".join(str(part).strip() for part in output).strip()
        else:
            text = str(output).strip()
        return text, language or "en"

    @staticmethod
    def _probe_duration(audio_path: Path) -> float:
        """
        Best-effort audio duration in seconds.

        Uses the stdlib ``wave`` module for WAV inputs (no extra dependency);
        returns ``0.0`` when the duration cannot be determined (Moonshine does
        not report it, and duration is metadata, not load-bearing).

        Args:
            audio_path: Path to the audio file.

        Returns:
            Duration in seconds, or ``0.0`` if undetermined.
        """
        with contextlib.suppress(Exception):
            with wave.open(str(audio_path), "rb") as wav:
                frames = wav.getnframes()
                rate = wav.getframerate()
                if rate:
                    return frames / float(rate)
        return 0.0

    async def close(self) -> None:
        """
        Release the Moonshine runtime reference.

        Clears the internal transcribe-callable reference to allow garbage
        collection of any loaded model state.
        """
        if self._transcribe_fn is not None:
            self.logger.debug("MoonshineSTTBackend: releasing model")
            self._transcribe_fn = None
