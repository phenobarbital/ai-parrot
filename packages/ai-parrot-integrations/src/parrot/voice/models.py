"""
Voice Module Data Models

Defines the data structures for voice interactions, including
audio chunks, voice messages, and response formats.

FEAT-416: ``VoiceConfig`` here has been replaced by a deprecation-warning
re-export of the unified ``parrot.models.voice.VoiceConfig`` (core) — see
``__getattr__`` at the bottom of this module. ``VoiceProvider`` has moved
to ``parrot.models.voice`` too and is re-exported below (a move, not a
rename, so no deprecation warning is raised for it).
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
import base64
import warnings

from parrot.models.voice import VoiceConfig as _VoiceConfig
from parrot.models.voice import VoiceProvider  # noqa: F401 — re-exported, no warning (a move)


class AudioFormat(Enum):
    """Supported audio formats for voice streaming."""
    PCM_16K = "audio/pcm;rate=16000"  # Input format for Gemini
    PCM_24K = "audio/pcm;rate=24000"  # Output format from Gemini
    WAV = "audio/wav"
    MP3 = "audio/mp3"
    OGG_OPUS = "audio/ogg;codecs=opus"
    WEBM_OPUS = "audio/webm;codecs=opus"


class SessionState(Enum):
    """Voice session states."""
    IDLE = "idle"
    CONNECTING = "connecting"
    ACTIVE = "active"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    ERROR = "error"
    CLOSED = "closed"


@dataclass
class VoiceChunk:
    """
    Represents a chunk of audio data in a voice stream.
    
    Can be used for both input (user speech) and output (agent speech).
    """
    data: bytes
    format: AudioFormat = AudioFormat.PCM_16K
    timestamp: datetime = field(default_factory=datetime.now)
    is_final: bool = False
    sequence: int = 0
    
    def to_base64(self) -> str:
        """Encode audio data to base64 for WebSocket transmission."""
        return base64.b64encode(self.data).decode('utf-8')
    
    @classmethod
    def from_base64(cls, b64_data: str, format: AudioFormat = AudioFormat.PCM_16K) -> 'VoiceChunk':
        """Create VoiceChunk from base64 encoded data."""
        return cls(
            data=base64.b64decode(b64_data),
            format=format
        )
    
    @property
    def duration_ms(self) -> float:
        """Estimate duration in milliseconds based on format and data size."""
        if self.format == AudioFormat.PCM_16K:
            # 16-bit samples (2 bytes) at 16kHz
            samples = len(self.data) / 2
            return (samples / 16000) * 1000
        elif self.format == AudioFormat.PCM_24K:
            samples = len(self.data) / 2
            return (samples / 24000) * 1000
        return 0.0


@dataclass
class VoiceMessage:
    """
    Represents a complete voice message in a conversation.
    
    Contains both the audio data and optional transcription.
    """
    id: str
    role: str  # "user" or "assistant"
    audio_data: Optional[bytes] = None
    audio_format: AudioFormat = AudioFormat.PCM_16K
    transcription: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "role": self.role,
            "audio_base64": base64.b64encode(self.audio_data).decode() if self.audio_data else None,
            "audio_format": self.audio_format.value,
            "transcription": self.transcription,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "metadata": self.metadata
        }


@dataclass
class VoiceResponse:
    """
    Response from a voice interaction.
    
    Contains both text and audio components for multimodal output.
    """
    text: str
    audio_data: Optional[bytes] = None
    audio_format: AudioFormat = AudioFormat.PCM_24K
    is_complete: bool = False
    is_interrupted: bool = False
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_websocket_message(self) -> Dict[str, Any]:
        """
        Format response for WebSocket transmission.
        
        Returns a dictionary that can be JSON-serialized and sent to the client.
        """
        return {
            "type": "voice_response",
            "text": self.text,
            "audio_base64": base64.b64encode(self.audio_data).decode() if self.audio_data else None,
            "audio_format": self.audio_format.value,
            "is_complete": self.is_complete,
            "is_interrupted": self.is_interrupted,
            "tool_calls": self.tool_calls,
            "metadata": self.metadata
        }


# =============================================================================
# FEAT-416: VoiceConfig deprecation shim
# =============================================================================
# VoiceConfig used to be defined here (17 fields, provider: VoiceProvider).
# It is now unified in parrot.models.voice (core) — see that module's
# docstring for the merge rationale. Importing VoiceConfig from this
# integrations module still works, but emits a DeprecationWarning pointing
# callers at the new location.

def __getattr__(name: str):
    if name == "VoiceConfig":
        warnings.warn(
            "Import VoiceConfig from parrot.models.voice instead",
            DeprecationWarning, stacklevel=2,
        )
        return _VoiceConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
