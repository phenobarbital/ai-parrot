"""
Shared Voice Module.

Provides voice transcription and text-to-speech synthesis capabilities
that can be used by any integration (MS Teams, Telegram, etc.).

Submodules:
- ``parrot.voice.transcriber`` — STT (speech-to-text) backends + VoiceTranscriber
- ``parrot.voice.tts`` — TTS (text-to-speech) backends + VoiceSynthesizer
"""
# Convenience re-export of the TTS synthesizer (FEAT-213).
# Full TTS surface is available via: from parrot.voice.tts import ...
from .tts import VoiceSynthesizer

__all__ = [
    "VoiceSynthesizer",
]
