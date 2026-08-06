"""Core voice package (FEAT-416).

Exposes :class:`VoiceSession`, the provider-agnostic voice turn lifecycle
manager promoted from the ``examples/clients/nova/audio.py`` demo. See
``parrot.voice.session`` for details.
"""
from .session import VoiceSession

__all__ = ("VoiceSession",)
