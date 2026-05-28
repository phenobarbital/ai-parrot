"""
Voice Transcriber Service — backward compatibility re-export.

The implementation has moved to `parrot.voice.transcriber.transcriber`.
This module re-exports for backward compatibility.
"""
import aiohttp  # noqa: F401 — kept for backward-compat mock paths

from parrot.voice.transcriber.transcriber import VoiceTranscriber

__all__ = ["VoiceTranscriber"]
