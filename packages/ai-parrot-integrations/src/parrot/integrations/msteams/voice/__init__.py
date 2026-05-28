"""
MS Teams Voice Module.

Provides voice transcription capabilities for MS Teams integration,
enabling agents to process voice note attachments from users.

Part of FEAT-008: MS Teams Voice Note Support.

Note: The core transcription infrastructure has been refactored to
`parrot.voice.transcriber` (FEAT-039) for sharing across integrations.
This module re-exports those symbols for backward compatibility and
keeps only MS Teams-specific components (AudioAttachment).
"""
from parrot.voice.transcriber import (
    AbstractTranscriberBackend,
    FasterWhisperBackend,
    OpenAIWhisperBackend,
    TranscriberBackend,
    TranscriptionResult,
    VoiceTranscriber,
    VoiceTranscriberConfig,
)

from .models import AudioAttachment

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
    # MS Teams-specific
    "AudioAttachment",
]
