"""
Abstract TTS Backend.

Defines the abstract base class for text-to-speech synthesis backends.
Concrete implementations (GoogleTTSBackend, and future ElevenLabs/OpenAI
backends) must implement the ``synthesize`` method.

Added by FEAT-213 (Telegram Voice Reply TTS Output).
Mirrors the structure of ``parrot.voice.transcriber.backend`` for symmetry.
"""
from abc import ABC, abstractmethod
from typing import Optional

from .models import SynthesisResult


class AbstractTTSBackend(ABC):
    """
    Abstract base class for text-to-speech synthesis backends.

    All TTS backends must implement the ``synthesize`` method. The optional
    ``close`` method may be overridden to release held resources (network
    connections, loaded models, etc.).

    Example::

        class MyBackend(AbstractTTSBackend):
            async def synthesize(self, text, *, voice=None, mime_format="audio/ogg"):
                audio_bytes = await my_tts_api(text, voice=voice)
                return SynthesisResult(audio=audio_bytes, mime_format=mime_format)

        backend = MyBackend()
        result = await backend.synthesize("Hello, world!")
        await backend.close()
    """

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        mime_format: str = "audio/ogg",
        language: Optional[str] = None,
    ) -> SynthesisResult:
        """
        Synthesize speech from text.

        Args:
            text: The text to convert to speech. Must be non-empty.
            voice: Backend-specific voice identifier (e.g. ``"Charon"`` for
                Google TTS). If ``None``, the backend uses its own default.
            mime_format: Desired MIME type of the audio output. Backends
                should honour this when possible; they may return a different
                format if the requested one is not supported and must reflect
                the actual format in ``SynthesisResult.mime_format``.
            language: BCP-47 language tag (e.g. ``"en-US"``). ``None``
                delegates language selection to the backend.

        Returns:
            ``SynthesisResult`` containing the raw audio bytes and the MIME
            type of the returned audio.

        Raises:
            ValueError: If ``text`` is empty or invalid for this backend.
            RuntimeError: If synthesis fails due to backend or network errors.

        Example::

            result = await backend.synthesize(
                "Buenos días, ¿en qué te puedo ayudar?",
                voice="Kore",
                mime_format="audio/ogg",
                language="es-ES",
            )
            print(f"Audio size: {len(result.audio)} bytes")
        """
        ...

    async def close(self) -> None:
        """
        Release resources held by the backend.

        This method should be called when the backend is no longer needed
        to free up resources such as network connections, loaded models,
        or API sessions.

        The default implementation does nothing. Subclasses should override
        this method if they hold resources that require explicit cleanup.

        Example::

            backend = GoogleTTSBackend()
            try:
                result = await backend.synthesize("Hello!")
            finally:
                await backend.close()
        """
        pass
