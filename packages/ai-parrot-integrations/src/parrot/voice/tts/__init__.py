"""
TTS (Text-to-Speech) Module.

Provides text-to-speech synthesis capabilities for voice reply in
Telegram and other integrations.

Supported backends:
- Google TTS: Cloud-based synthesis via GoogleGenAIClient.generate_speech

Future backends (architecture ready, not yet implemented):
- ElevenLabs: reserved (raises ValueError)
- OpenAI TTS: reserved (raises ValueError)

Added by FEAT-213 (Telegram Voice Reply TTS Output).
Mirrors the structure of ``parrot.voice.transcriber`` for symmetry.
"""
from .backend import AbstractTTSBackend
from .google_backend import GoogleTTSBackend
from .models import SynthesisResult, TTSConfig
from .synthesizer import VoiceSynthesizer

__all__ = [
    # Service
    "VoiceSynthesizer",
    # Backend Abstract
    "AbstractTTSBackend",
    # Backend Implementations
    "GoogleTTSBackend",
    # Config and Results
    "TTSConfig",
    "SynthesisResult",
]
