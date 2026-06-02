"""
Google TTS Backend.

Implements AbstractTTSBackend using GoogleGenAIClient.generate_speech.
This is the default backend for VoiceSynthesizer.

The audio returned by ``generate_speech`` is raw PCM data (Gemini TTS
produces 24kHz mono 16-bit PCM). The actual container format—and therefore
the ``mime_format`` field in the returned ``SynthesisResult``—is whatever
was requested via the ``mime_format`` argument; note that Telegram voice
notes prefer OGG/Opus, so container conversion is handled by the caller
(TASK-1409 / Telegram wrapper).

Added by FEAT-213 (Telegram Voice Reply TTS Output).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from .backend import AbstractTTSBackend
from .models import SynthesisResult

if TYPE_CHECKING:
    from parrot.clients.google.generation import GoogleGenAIClient

# Default voice when none is specified in the config
_DEFAULT_VOICE = "Charon"


class GoogleTTSBackend(AbstractTTSBackend):
    """
    TTS backend that wraps ``GoogleGenAIClient.generate_speech``.

    Builds a ``SpeechGenerationPrompt`` with a single ``SpeakerConfig``
    and calls ``generate_speech``; then extracts the raw audio bytes from
    the returned ``AIMessage.output``.

    Args:
        client: An already-instantiated ``GoogleGenAIClient``. When
            ``None`` (default), a new client is created lazily on first
            use. Providing an explicit client is the recommended pattern
            for unit testing (dependency injection).
        voice: Default voice identifier to use when the caller does not
            supply one (e.g. ``"Charon"``, ``"Kore"``, ``"Puck"``).
            Falls back to ``"Charon"`` when ``None``.
        **kwargs: Extra keyword arguments are accepted and ignored to
            allow forward-compatible construction.

    Example::

        backend = GoogleTTSBackend(voice="Kore")
        result = await backend.synthesize("Hello, world!")
        print(f"Audio: {len(result.audio)} bytes, format: {result.mime_format}")
    """

    def __init__(
        self,
        client: Optional["GoogleGenAIClient"] = None,
        *,
        voice: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Initialize the Google TTS backend.

        Args:
            client: An already-instantiated ``GoogleGenAIClient``. When
                ``None`` (default), a new client is created lazily on first
                use using any remaining ``**kwargs`` (e.g. ``api_key=``,
                ``model=``).
            voice: Default voice identifier. Falls back to ``"Charon"``.
            **kwargs: Extra keyword arguments forwarded verbatim to
                ``GoogleGenAIClient(**kwargs)`` during lazy creation.
        """
        self._client = client
        self._default_voice = voice or _DEFAULT_VOICE
        self._client_kwargs: dict = kwargs
        self.logger = logging.getLogger(__name__)

    def _get_client(self) -> "GoogleGenAIClient":
        """
        Get or lazily create the GoogleGenAIClient.

        Returns:
            A ``GoogleGenAIClient`` instance.
        """
        if self._client is None:
            from parrot.clients.google.generation import GoogleGenAIClient

            self.logger.debug(
                "GoogleTTSBackend: creating GoogleGenAIClient lazily (kwargs=%s)",
                list(self._client_kwargs.keys()),
            )
            self._client = GoogleGenAIClient(**self._client_kwargs)
        return self._client

    async def synthesize(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        mime_format: str = "audio/ogg",
        language: Optional[str] = None,
    ) -> SynthesisResult:
        """
        Synthesize speech from text using the Google TTS API.

        Builds a single-speaker ``SpeechGenerationPrompt``, calls
        ``GoogleGenAIClient.generate_speech``, and returns the raw PCM audio
        bytes packed in a ``SynthesisResult``.

        Note:
            The Google backend always returns **raw PCM** (24 kHz, mono,
            16-bit little-endian). The ``mime_format`` argument is passed
            through to ``SynthesisResult.mime_format`` for the caller's
            reference, but no container conversion is performed here. The
            caller (e.g. the Telegram wrapper) is responsible for converting
            the PCM bytes to OGG/Opus before sending as a Telegram voice note.

        Args:
            text: The text to convert to speech. Must be non-empty.
            voice: Voice identifier (e.g. ``"Charon"``). Falls back to
                the ``voice`` supplied at construction time, then to
                ``"Charon"``.
            mime_format: Requested MIME type label stored in the returned
                ``SynthesisResult.mime_format``. Does NOT affect the actual
                encoding — raw PCM is always returned.
            language: BCP-47 language tag forwarded to
                ``SpeechGenerationPrompt.language`` (e.g. ``"es-ES"``).
                ``None`` leaves the prompt at its default (``"en-US"``).

        Returns:
            ``SynthesisResult`` with the raw PCM audio bytes and the
            ``mime_format`` label that was requested.

        Raises:
            ValueError: If ``text`` is empty.
            RuntimeError: If ``generate_speech`` returns no audio data.

        Example::

            result = await backend.synthesize(
                "Buenos días, ¿cómo estás?",
                voice="Kore",
                mime_format="audio/ogg",
                language="es-ES",
            )
        """
        if not text or not text.strip():
            raise ValueError("text must not be empty")

        effective_voice = voice or self._default_voice

        from parrot.models.outputs import SpeakerConfig, SpeechGenerationPrompt

        speaker = SpeakerConfig(name="Narrator", voice=effective_voice)
        prompt_kwargs: dict = {"prompt": text, "speakers": [speaker]}
        if language is not None:
            prompt_kwargs["language"] = language
        prompt = SpeechGenerationPrompt(**prompt_kwargs)

        self.logger.debug(
            "GoogleTTSBackend: synthesizing %d chars with voice=%s",
            len(text),
            effective_voice,
        )

        client = self._get_client()
        ai_message = await client.generate_speech(prompt)

        # Audio bytes live in AIMessage.output (raw PCM from Gemini TTS).
        # ai_message.files is only populated when output_directory was passed
        # to generate_speech — we do not pass one, so we always use .output.
        audio_bytes = ai_message.output
        if not audio_bytes:
            raise RuntimeError(
                "GoogleGenAIClient.generate_speech returned no audio data"
            )

        self.logger.debug(
            "GoogleTTSBackend: received %d bytes of audio (mime=%s)",
            len(audio_bytes),
            mime_format,
        )

        return SynthesisResult(audio=audio_bytes, mime_format=mime_format)

    async def close(self) -> None:
        """
        Release backend resources.

        The Google client does not require explicit teardown, but this
        method clears the internal reference to allow garbage collection.
        """
        self._client = None
