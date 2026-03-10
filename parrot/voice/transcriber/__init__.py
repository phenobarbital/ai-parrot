"""
Shared Voice Transcription Module.

Provides voice transcription capabilities for all integrations
(MS Teams, Telegram, etc.) using pluggable backends.

Supported backends:
- FasterWhisper: Local GPU-accelerated transcription
- OpenAI Whisper: Cloud-based transcription via OpenAI API

Originally part of FEAT-008 (MS Teams Voice Note Support),
refactored to shared location for FEAT-039 (Telegram Voice Note Support).
"""
from .backend import AbstractTranscriberBackend
from .faster_whisper_backend import FasterWhisperBackend
from .models import (
    TranscriberBackend,
    TranscriptionResult,
    VoiceTranscriberConfig,
)
from .openai_backend import OpenAIWhisperBackend
from .transcriber import VoiceTranscriber

__all__ = [
    # Service
    "VoiceTranscriber",
    # Backend Abstract
    "AbstractTranscriberBackend",
    # Backend Implementations
    "FasterWhisperBackend",
    "OpenAIWhisperBackend",
    # Enums and Config
    "TranscriberBackend",
    "VoiceTranscriberConfig",
    # Results
    "TranscriptionResult",
]
