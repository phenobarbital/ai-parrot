"""
Faster Whisper Backend — backward compatibility re-export.

The implementation has moved to `parrot.voice.transcriber.faster_whisper_backend`.
This module re-exports for backward compatibility.
"""
from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend

__all__ = ["FasterWhisperBackend"]
