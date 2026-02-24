"""
Voice Transcription Data Models.

Pydantic models for voice transcription configuration, results,
and MS Teams audio attachment parsing.

Part of FEAT-008: MS Teams Voice Note Support.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TranscriberBackend(str, Enum):
    """
    Available transcription backends.

    - FASTER_WHISPER: Local GPU-accelerated transcription using faster-whisper
    - OPENAI_WHISPER: Cloud-based transcription using OpenAI Whisper API
    """

    FASTER_WHISPER = "faster_whisper"
    OPENAI_WHISPER = "openai_whisper"


class VoiceTranscriberConfig(BaseModel):
    """
    Configuration for voice transcription.

    Controls which backend to use, model settings, and behavior options.
    """

    enabled: bool = Field(
        default=True,
        description="Enable voice note processing"
    )
    backend: TranscriberBackend = Field(
        default=TranscriberBackend.FASTER_WHISPER,
        description="Transcription backend to use"
    )
    model_size: str = Field(
        default="small",
        description="Whisper model size (tiny, base, small, medium, large-v3)"
    )
    language: Optional[str] = Field(
        default=None,
        description="Force language (ISO 639-1 code, e.g., 'en', 'es'). None = auto-detect"
    )
    show_transcription: bool = Field(
        default=True,
        description="Show transcription to user before processing"
    )
    max_audio_duration_seconds: int = Field(
        default=60,
        ge=1,
        le=300,
        description="Max audio duration to process (seconds)"
    )
    openai_api_key: Optional[str] = Field(
        default=None,
        description="OpenAI API key (required if using openai_whisper backend)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "enabled": True,
                    "backend": "faster_whisper",
                    "model_size": "small",
                    "show_transcription": True,
                    "max_audio_duration_seconds": 60,
                },
                {
                    "enabled": True,
                    "backend": "openai_whisper",
                    "openai_api_key": "sk-...",
                    "language": "en",
                },
            ]
        }
    }


class TranscriptionResult(BaseModel):
    """
    Result of voice transcription.

    Contains the transcribed text along with metadata about
    the audio and processing.
    """

    text: str = Field(
        ...,
        description="Transcribed text"
    )
    language: str = Field(
        ...,
        description="Detected or specified language code (ISO 639-1)"
    )
    duration_seconds: float = Field(
        ...,
        ge=0,
        description="Audio duration in seconds"
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score if available (0.0 to 1.0)"
    )
    processing_time_ms: int = Field(
        ...,
        ge=0,
        description="Transcription processing time in milliseconds"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "text": "Hello, how can I help you today?",
                    "language": "en",
                    "duration_seconds": 3.5,
                    "confidence": 0.95,
                    "processing_time_ms": 850,
                }
            ]
        }
    }


class AudioAttachment(BaseModel):
    """
    Parsed audio attachment from MS Teams.

    Represents an audio file attachment that can be downloaded
    and transcribed.
    """

    content_url: str = Field(
        ...,
        description="URL to download audio from MS Teams CDN"
    )
    content_type: str = Field(
        ...,
        description="MIME type (e.g., 'audio/ogg', 'audio/mp4')"
    )
    name: Optional[str] = Field(
        default=None,
        description="Original filename"
    )
    size_bytes: Optional[int] = Field(
        default=None,
        ge=0,
        description="File size in bytes"
    )

    @property
    def is_voice_note(self) -> bool:
        """Check if this is a supported audio format for voice notes."""
        supported_types = {
            "audio/ogg",
            "audio/mpeg",
            "audio/mp3",
            "audio/wav",
            "audio/x-wav",
            "audio/mp4",
            "audio/m4a",
            "audio/webm",
            "video/webm",  # WebM can contain audio
        }
        content_lower = self.content_type.lower()
        return any(ct in content_lower for ct in supported_types)

    @property
    def file_extension(self) -> str:
        """Get file extension from content type."""
        type_to_ext = {
            "audio/ogg": ".ogg",
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/mp4": ".m4a",
            "audio/m4a": ".m4a",
            "audio/webm": ".webm",
            "video/webm": ".webm",
        }
        content_lower = self.content_type.lower()
        for mime, ext in type_to_ext.items():
            if mime in content_lower:
                return ext
        return ".wav"  # fallback

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "content_url": "https://teams.microsoft.com/files/audio123.ogg",
                    "content_type": "audio/ogg",
                    "name": "voice_note.ogg",
                    "size_bytes": 24576,
                }
            ]
        }
    }
