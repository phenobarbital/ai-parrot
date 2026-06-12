"""
Voice Synthesizer Service.

Main service that orchestrates text-to-speech synthesis. Selects the
appropriate backend based on configuration, manages the backend lifecycle,
and provides a unified ``synthesize(text)`` interface used by integration
wrappers (Telegram, etc.).

Mirrors the structure of ``parrot.voice.transcriber.transcriber.VoiceTranscriber``.
Added by FEAT-213 (Telegram Voice Reply TTS Output).
"""

from __future__ import annotations

import logging
from typing import Optional

from .backend import AbstractTTSBackend
from .models import SynthesisResult, TTSConfig


class VoiceSynthesizer:
    """
    Text-to-speech synthesis service.

    Manages the TTS backend lifecycle and provides a unified interface for
    synthesizing speech from text strings.

    The backend is lazily created on first use. Call ``close()`` to release
    backend resources when done.

    Args:
        config: TTS configuration including backend selection, voice, and
            audio format. Defaults to ``TTSConfig()`` (Google backend,
            ``"audio/ogg"`` output) when ``None``.

    Example::

        synth = VoiceSynthesizer(TTSConfig(backend="google", voice="Charon"))
        try:
            result = await synth.synthesize("Hello from the bot!")
            # result.audio holds the raw audio bytes
        finally:
            await synth.close()
    """

    def __init__(self, config: Optional[TTSConfig] = None) -> None:
        """Initialize the voice synthesizer with optional config."""
        self.config = config or TTSConfig()
        self.logger = logging.getLogger(__name__)
        self._backend: Optional[AbstractTTSBackend] = None

    def _get_backend(self) -> AbstractTTSBackend:
        """
        Get or lazily create the TTS backend.

        Creates the backend on first call based on ``self.config.backend``.
        Subsequent calls return the cached instance.

        Returns:
            The TTS backend instance.

        Raises:
            ValueError: If the configured backend is not yet implemented
                (``"elevenlabs"``, ``"openai"``) or is unknown.

        Example::

            synth = VoiceSynthesizer(TTSConfig(backend="google"))
            backend = synth._get_backend()  # GoogleTTSBackend created here
        """
        if self._backend is None:
            backend_name = self.config.backend
            if backend_name == "google":
                from .google_backend import GoogleTTSBackend

                self.logger.info(
                    "VoiceSynthesizer: creating GoogleTTSBackend (voice=%s)",
                    self.config.voice,
                )
                self._backend = GoogleTTSBackend(voice=self.config.voice)
            elif backend_name == "supertonic":
                from .supertonic_inference import SupertonicONNXBackend

                self.logger.info(
                    "VoiceSynthesizer: creating SupertonicONNXBackend " "(voice=%s, total_step=%d, speed=%.2f)",
                    self.config.voice,
                    self.config.total_step,
                    self.config.speed,
                )
                self._backend = SupertonicONNXBackend(
                    voice=self.config.voice,
                    total_step=self.config.total_step,
                    speed=self.config.speed,
                )
            elif backend_name in ("elevenlabs", "openai"):
                raise ValueError(
                    f"TTS backend not implemented: '{backend_name}'. "
                    "Available backends: 'google', 'supertonic' (FEAT-231)."
                )
            else:
                raise ValueError(
                    f"Unknown TTS backend: '{backend_name}'. "
                    "Supported values: 'google', 'supertonic', "
                    "'elevenlabs', 'openai'."
                )
        return self._backend

    async def synthesize(
        self,
        text: str,
        *,
        language: Optional[str] = None,
    ) -> SynthesisResult:
        """
        Synthesize speech from text.

        Delegates to the backend selected by ``self.config.backend``.
        Uses the voice and MIME format from the configuration.

        Args:
            text: The text to convert to speech. Must be non-empty.
            language: BCP-47 language tag (e.g. ``"en-US"``). When
                ``None``, the value from ``self.config.language`` is used
                as a fallback; if that is also ``None`` the backend applies
                its own default.

        Returns:
            ``SynthesisResult`` containing the raw audio bytes and the
            actual MIME format of the audio data.

        Raises:
            ValueError: If ``text`` is empty, or if the backend is not
                implemented.
            RuntimeError: If the underlying TTS API returns no audio.

        Example::

            result = await synth.synthesize(
                "Hola, ¿en qué te puedo ayudar?",
                language="es-ES",
            )
            print(f"Audio size: {len(result.audio)} bytes")
        """
        backend = self._get_backend()
        effective_language = language if language is not None else self.config.language
        return await backend.synthesize(
            text,
            voice=self.config.voice,
            mime_format=self.config.mime_format,
            language=effective_language,
        )

    async def close(self) -> None:
        """
        Release backend resources.

        Should be called when the synthesizer is no longer needed to free
        up any resources held by the backend (API sessions, etc.).
        """
        if self._backend is not None:
            self.logger.debug("VoiceSynthesizer: closing backend")
            await self._backend.close()
            self._backend = None
