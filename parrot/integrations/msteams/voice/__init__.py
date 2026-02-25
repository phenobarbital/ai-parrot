"""
MS Teams Voice Module.

Provides voice transcription capabilities for MS Teams integration,
enabling agents to process voice note attachments from users.

Part of FEAT-008: MS Teams Voice Note Support.
"""
from .backend import AbstractTranscriberBackend
from .faster_whisper_backend import FasterWhisperBackend
from .models import (
    AudioAttachment,
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
    "AudioAttachment",
]
