"""
AI-Parrot Voice Module

Provides real-time voice interaction capabilities for AI agents using
native speech-to-speech models (Gemini Live API, OpenAI Realtime API).

Key Components:
- VoiceSession: Manages bidirectional voice streaming sessions
- VoiceBot: Bot implementation with voice capabilities
- Providers: Gemini Live, OpenAI Realtime, Whisper fallback
"""

from .session import VoiceSession
from .models import (
    VoiceConfig,
    VoiceMessage,
    VoiceChunk,
    VoiceResponse,
    AudioFormat,
    SessionState,
)

__all__ = [
    "VoiceSession",
    "VoiceConfig",
    "VoiceMessage",
    "VoiceChunk",
    "VoiceResponse",
    "AudioFormat",
    "SessionState",
]
