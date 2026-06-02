"""
TTS Data Models.

Pydantic models for text-to-speech configuration and synthesis results.
These models are shared across all TTS backends (Google, ElevenLabs, etc.)
and the VoiceSynthesizer service.

Added by FEAT-213 (Telegram Voice Reply TTS Output).
Mirrors the structure of ``parrot.voice.transcriber.models`` for symmetry.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class TTSConfig(BaseModel):
    """
    Configuration for text-to-speech synthesis.

    Controls which backend to use and the audio output format.
    All fields are optional; defaults produce a Google TTS backend
    with OGG/Opus output (the preferred format for Telegram voice notes).

    Attributes:
        backend: TTS backend to use. Currently only ``"google"`` is
            implemented; ``"elevenlabs"`` and ``"openai"`` are reserved
            for future use and will raise ``ValueError`` at runtime.
        voice: Backend-specific voice identifier (e.g. ``"Charon"``,
            ``"Kore"`` for the Google backend). ``None`` falls back to
            the backend's default voice.
        language: BCP-47 language tag (e.g. ``"en-US"``). ``None``
            delegates language selection to the backend.
        mime_format: MIME type of the desired audio output. Telegram
            voice notes prefer ``"audio/ogg"`` (OGG/Opus).

    Example::

        cfg = TTSConfig(backend="google", voice="Charon", language="en-US")
    """

    backend: Literal["google", "elevenlabs", "openai"] = Field(
        default="google",
        description="TTS backend to use (only 'google' is implemented in FEAT-213)",
    )
    voice: Optional[str] = Field(
        default=None,
        description="Backend-specific voice ID (e.g. 'Charon', 'Kore' for Google)",
    )
    language: Optional[str] = Field(
        default=None,
        description="BCP-47 language tag (e.g. 'en-US'). None = backend default",
    )
    mime_format: str = Field(
        default="audio/ogg",
        description="Desired audio MIME type. Telegram voice notes prefer 'audio/ogg'",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "backend": "google",
                    "voice": "Charon",
                    "language": "en-US",
                    "mime_format": "audio/ogg",
                },
                {
                    "backend": "google",
                    "mime_format": "audio/wav",
                },
            ]
        }
    }


class SynthesisResult(BaseModel):
    """
    Result of a text-to-speech synthesis call.

    Contains the raw audio bytes and metadata about the synthesized audio.

    Attributes:
        audio: Raw audio bytes as produced by the backend. The actual
            container format matches ``mime_format`` (e.g. WAV PCM bytes
            for ``"audio/wav"``).
        mime_format: MIME type of the audio data (e.g. ``"audio/wav"``,
            ``"audio/ogg"``).
        duration_s: Duration of the synthesized audio in seconds.
            ``None`` when not available from the backend.

    Example::

        result = SynthesisResult(audio=b"...", mime_format="audio/ogg")
        assert result.duration_s is None  # not populated unless backend provides it
    """

    audio: bytes = Field(
        ...,
        description=(
            "Raw audio bytes. For the Google backend this is always raw PCM "
            "(24 kHz, mono, 16-bit LE); the caller must convert to OGG/Opus "
            "before sending as a Telegram voice note."
        ),
    )
    mime_format: str = Field(
        ...,
        description="MIME type of the audio data (e.g. 'audio/wav', 'audio/ogg')",
    )
    duration_s: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Duration in seconds (None if not provided by the backend)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "audio": "<base64-encoded PCM audio>",
                    "mime_format": "audio/pcm",
                    "duration_s": 3.2,
                }
            ]
        }
    }
