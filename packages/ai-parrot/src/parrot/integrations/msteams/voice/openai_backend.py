"""
OpenAI Whisper Backend — backward compatibility re-export.

The implementation has moved to `parrot.voice.transcriber.openai_backend`.
This module re-exports for backward compatibility.
"""
from parrot.voice.transcriber.openai_backend import OpenAIWhisperBackend

__all__ = ["OpenAIWhisperBackend"]
