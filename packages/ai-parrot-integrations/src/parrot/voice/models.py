"""
Voice Module Data Models

Defines the data structures for voice interactions, including
audio chunks, voice messages, and response formats.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
import base64


class AudioFormat(Enum):
    """Supported audio formats for voice streaming."""
    PCM_16K = "audio/pcm;rate=16000"  # Input format for Gemini
    PCM_24K = "audio/pcm;rate=24000"  # Output format from Gemini
    WAV = "audio/wav"
    MP3 = "audio/mp3"
    OGG_OPUS = "audio/ogg;codecs=opus"
    WEBM_OPUS = "audio/webm;codecs=opus"


class VoiceProvider(Enum):
    """Supported voice providers."""
    GOOGLE_LIVE = "google_live"
    OPENAI_REALTIME = "openai_realtime"
    WHISPER_TTS = "whisper_tts"  # Fallback: Whisper STT + LLM + TTS


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


@dataclass 
class VoiceConfig:
    """
    Configuration for voice sessions.
    
    Defines audio parameters, provider settings, and behavior options.
    """
    # Provider selection
    provider: VoiceProvider = VoiceProvider.GOOGLE_LIVE
    
    # Audio settings
    input_format: AudioFormat = AudioFormat.PCM_16K
    output_format: AudioFormat = AudioFormat.PCM_24K
    input_sample_rate: int = 16000
    output_sample_rate: int = 24000
    
    # Voice settings (provider-specific)
    voice_name: str = "Puck"  # Gemini: Aoede, Charon, Fenrir, Kore, Puck
    language: str = "en-US"
    
    # Session behavior
    enable_vad: bool = True  # Voice Activity Detection
    vad_mode: str = "server_vad"  # server_vad, semantic_vad, none
    enable_interruption: bool = True
    
    # Transcription
    enable_input_transcription: bool = True
    enable_output_transcription: bool = True
    
    # Timeouts
    session_timeout_seconds: int = 1800  # 30 minutes
    silence_timeout_seconds: int = 30
    
    # Model settings
    model: Optional[str] = None  # Auto-select based on provider
    temperature: float = 0.7
    max_tokens: int = 4096
    
    def get_model(self) -> str:
        """Get the appropriate model string for the provider."""
        if self.model:
            return self.model
        
        if self.provider == VoiceProvider.GOOGLE_LIVE:
            return "gemini-2.5-flash-native-audio-preview-09-2025"
        elif self.provider == VoiceProvider.OPENAI_REALTIME:
            return "gpt-realtime"
        else:
            return "gemini-2.5-flash"  # Fallback
    
    def to_gemini_config(self) -> Dict[str, Any]:
        """Convert to Gemini Live API configuration format."""
        return {
            "response_modalities": ["AUDIO", "TEXT"],
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {
                        "voice_name": self.voice_name
                    }
                },
            },
            "realtime_input_config": {
                "automatic_activity_detection": {
                    "disabled": not self.enable_vad
                }
            },
            "generation_config": {
                "temperature": self.temperature,
                "max_output_tokens": self.max_tokens
            }
        }