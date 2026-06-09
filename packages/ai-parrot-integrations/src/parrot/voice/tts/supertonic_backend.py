"""
Supertonic TTS Backend.

Implements :class:`AbstractTTSBackend` against the Supertonic sub-second
text-to-speech model (ONNX runtime + weights). Mirrors the structure of
:class:`GoogleTTSBackend`: the heavy ONNX session is created lazily on first
synthesis, and inference runs off the event loop via ``asyncio.to_thread``.

Unlike the Google backend (which returns raw PCM and leaves container
conversion to the caller), this backend returns a **browser-playable WAV
container** by default and labels ``SynthesisResult.mime_format`` truthfully —
``mime_format`` is a label, not a converter, so the bytes always match the
label.

Extras-gated: the ONNX runtime and the Supertonic weights ship behind the
``ai-parrot-integrations[voice-supertonic]`` extra. When those dependencies
(or the model weights) are missing, ``synthesize`` raises ``ImportError`` /
``ValueError`` — it never silently degrades. Graceful degradation to
text-only is the *handler's* responsibility (FEAT-231, AgentVoiceTalk).

Added by FEAT-231 (AgentTalk Voice Support).
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import wave
from typing import Optional

from .backend import AbstractTTSBackend
from .models import SynthesisResult

# Default container/codec target. Supertonic emits raw PCM samples; we wrap
# them into a WAV container so the bytes are playable in a browser <audio>
# element without any further conversion.
_DEFAULT_MIME_FORMAT = "audio/wav"

# Supertonic produces 24 kHz mono 16-bit PCM (matches the upstream model card).
_SAMPLE_RATE = 24000
_CHANNELS = 1
_SAMPLE_WIDTH = 2  # bytes per sample (16-bit)

# Environment variable used to locate the Supertonic ONNX weights when no
# explicit ``model_path`` is supplied at construction time.
_MODEL_PATH_ENV = "SUPERTONIC_MODEL_PATH"


class SupertonicTTSBackend(AbstractTTSBackend):
    """
    TTS backend that wraps the Supertonic ONNX speech model.

    The ONNX inference session is created lazily on first ``synthesize`` call
    to keep construction cheap (so ``VoiceSynthesizer._get_backend`` can build
    the backend without paying the model-load cost). Inference runs in a worker
    thread via ``asyncio.to_thread`` so the event loop is never blocked.

    Args:
        voice: Default voice/speaker identifier to use when the caller does
            not supply one. ``None`` falls back to the Supertonic default
            speaker.
        model_path: Filesystem path to the Supertonic ONNX weights. When
            ``None`` (default), the ``SUPERTONIC_MODEL_PATH`` environment
            variable is consulted at synthesis time.
        sample_rate: Output PCM sample rate in Hz. Defaults to 24 kHz to
            match the Supertonic model card.
        **kwargs: Extra keyword arguments are accepted and ignored to allow
            forward-compatible construction.

    Example::

        backend = SupertonicTTSBackend(voice="default")
        result = await backend.synthesize("Hola, ¿en qué puedo ayudarte?")
        # result.audio is a playable WAV; result.mime_format == "audio/wav"
        await backend.close()
    """

    def __init__(
        self,
        voice: Optional[str] = None,
        *,
        model_path: Optional[str] = None,
        sample_rate: int = _SAMPLE_RATE,
        **kwargs,
    ) -> None:
        """Initialize the Supertonic TTS backend (no model load here)."""
        self.voice = voice
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.logger = logging.getLogger(__name__)
        # Lazily-created ONNX inference session (see ``_ensure_session``).
        self._session = None

    def _resolve_model_path(self) -> str:
        """
        Resolve the Supertonic ONNX weights path.

        Returns:
            The configured model path (constructor arg or environment).

        Raises:
            ValueError: If no model path is configured.
        """
        path = self.model_path or os.environ.get(_MODEL_PATH_ENV)
        if not path:
            raise ValueError(
                "Supertonic model weights not configured. Pass "
                "model_path=... or set the SUPERTONIC_MODEL_PATH environment "
                "variable to the Supertonic ONNX weights."
            )
        if not os.path.exists(path):
            raise ValueError(f"Supertonic model weights not found at: {path}")
        return path

    def _ensure_session(self) -> None:
        """
        Lazily create the ONNX inference session.

        Imports ``onnxruntime`` (shipped via the ``voice-supertonic`` extra)
        only when first needed, so server boot and backend construction never
        require the heavy dependency.

        Raises:
            ImportError: If ``onnxruntime`` (the ``voice-supertonic`` extra)
                is not installed.
            ValueError: If the Supertonic weights are not configured/found.
        """
        if self._session is not None:
            return
        try:
            import onnxruntime  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - exercised via stub
            raise ImportError(
                "Supertonic TTS backend requires 'onnxruntime'. Install the "
                "extra: pip install 'ai-parrot-integrations[voice-supertonic]'."
            ) from exc

        model_path = self._resolve_model_path()
        self.logger.info(
            "SupertonicTTSBackend: loading ONNX model from %s", model_path
        )
        self._session = onnxruntime.InferenceSession(model_path)
        self.logger.info("SupertonicTTSBackend: ONNX model loaded")

    async def synthesize(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        mime_format: str = "audio/ogg",
        language: Optional[str] = None,
    ) -> SynthesisResult:
        """
        Synthesize speech from text using Supertonic.

        Runs ONNX inference off the event loop, wraps the resulting PCM
        samples into a WAV container, and returns a ``SynthesisResult`` whose
        ``mime_format`` truthfully reflects the returned bytes.

        Args:
            text: The text to convert to speech. Must be non-empty.
            voice: Voice/speaker identifier. Falls back to the ``voice``
                supplied at construction time, then to the Supertonic default.
            mime_format: Requested MIME type. Only ``"audio/wav"`` is
                produced by this backend; any other value is normalised to
                ``"audio/wav"`` (the bytes are always a WAV container, so the
                returned ``mime_format`` stays truthful).
            language: BCP-47 language tag forwarded to the model. ``None``
                delegates language selection to the model default.

        Returns:
            ``SynthesisResult`` with playable WAV bytes and
            ``mime_format == "audio/wav"``.

        Raises:
            ValueError: If ``text`` is empty or the weights are unconfigured.
            RuntimeError: If inference produces no audio.
            ImportError: If the ``voice-supertonic`` extra is not installed.
        """
        if not text or not text.strip():
            raise ValueError("text must not be empty")

        effective_voice = voice or self.voice
        # The Supertonic container is always WAV; keep the label truthful even
        # if the caller requested a different MIME type.
        target_format = (
            mime_format if mime_format == _DEFAULT_MIME_FORMAT else _DEFAULT_MIME_FORMAT
        )

        self.logger.debug(
            "SupertonicTTSBackend: synthesizing %d chars (voice=%s, lang=%s)",
            len(text),
            effective_voice,
            language,
        )

        pcm_bytes = await asyncio.to_thread(
            self._synthesize_sync, text, effective_voice, language
        )
        if not pcm_bytes:
            raise RuntimeError("Supertonic synthesis returned no audio data")

        audio_bytes = self._pcm_to_wav(pcm_bytes)

        self.logger.debug(
            "SupertonicTTSBackend: produced %d bytes of WAV audio",
            len(audio_bytes),
        )
        return SynthesisResult(audio=audio_bytes, mime_format=target_format)

    def _synthesize_sync(
        self,
        text: str,
        voice: Optional[str],
        language: Optional[str],
    ) -> bytes:
        """
        Synchronous Supertonic inference (runs in a worker thread).

        Loads the ONNX session lazily, runs inference, and returns raw PCM
        bytes (16-bit little-endian mono at ``self.sample_rate``). This method
        is intentionally isolated so unit tests can stub it without touching
        the ONNX runtime.

        Args:
            text: The text to synthesize.
            voice: Resolved voice/speaker identifier (may be ``None``).
            language: Optional BCP-47 language tag.

        Returns:
            Raw PCM audio bytes (16-bit LE, mono, ``self.sample_rate`` Hz).
        """
        self._ensure_session()
        # The concrete Supertonic ONNX graph I/O (tokenisation, speaker
        # embeddings, output tensor name) is resolved against the installed
        # weights. We expose the raw inference here; the public ``synthesize``
        # handles WAV wrapping and the async offload. Tests stub this method.
        from supertonic import synthesize_pcm  # noqa: PLC0415

        return synthesize_pcm(
            self._session,
            text,
            voice=voice,
            language=language,
            sample_rate=self.sample_rate,
        )

    def _pcm_to_wav(self, pcm_bytes: bytes) -> bytes:
        """
        Wrap raw PCM samples into a WAV container.

        Uses the stdlib ``wave`` module (no extra dependency) so the returned
        bytes are a self-describing, browser-playable WAV file.

        Args:
            pcm_bytes: Raw PCM audio (16-bit LE, mono, ``self.sample_rate`` Hz).

        Returns:
            WAV-container audio bytes.
        """
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(_CHANNELS)
            wav.setsampwidth(_SAMPLE_WIDTH)
            wav.setframerate(self.sample_rate)
            wav.writeframes(pcm_bytes)
        return buffer.getvalue()

    async def close(self) -> None:
        """
        Release the ONNX inference session.

        Clears the internal session reference to allow garbage collection of
        the loaded model.
        """
        if self._session is not None:
            self.logger.debug("SupertonicTTSBackend: releasing ONNX session")
            self._session = None
