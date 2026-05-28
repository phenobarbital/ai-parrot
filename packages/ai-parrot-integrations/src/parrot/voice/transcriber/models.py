"""
Voice Transcription Data Models.

Pydantic models for voice transcription configuration and results.
These models are shared across all integrations that support voice input.

Originally part of FEAT-008 (MS Teams Voice Note Support),
refactored to shared location for FEAT-039.
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
