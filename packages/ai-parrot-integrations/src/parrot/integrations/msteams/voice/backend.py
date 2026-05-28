"""
Abstract Transcriber Backend — backward compatibility re-export.

The implementation has moved to `parrot.voice.transcriber.backend`.
This module re-exports for backward compatibility.
"""
from parrot.voice.transcriber.backend import AbstractTranscriberBackend

__all__ = ["AbstractTranscriberBackend"]
