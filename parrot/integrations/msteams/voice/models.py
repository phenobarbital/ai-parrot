"""
MS Teams Voice Data Models.

MS Teams-specific audio attachment model. Shared transcription models
(VoiceTranscriberConfig, TranscriptionResult, TranscriberBackend) have been
moved to `parrot.voice.transcriber.models` and are re-exported here
for backward compatibility.

Part of FEAT-008: MS Teams Voice Note Support.
"""
from typing import Optional

from pydantic import BaseModel, Field

# Re-export shared models for backward compatibility
from parrot.voice.transcriber.models import (  # noqa: F401
    TranscriberBackend,
    TranscriptionResult,
    VoiceTranscriberConfig,
)


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
