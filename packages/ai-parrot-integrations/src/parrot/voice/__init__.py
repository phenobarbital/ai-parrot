"""
Shared Voice Module.

Provides voice transcription and text-to-speech synthesis capabilities
that can be used by any integration (MS Teams, Telegram, etc.).

Submodules:
- ``parrot.voice.transcriber`` — STT (speech-to-text) backends + VoiceTranscriber
- ``parrot.voice.tts`` — TTS (text-to-speech) backends + VoiceSynthesizer
- ``parrot.voice.session`` / ``parrot.voice.handler`` / ``parrot.voice.models``
  — provided by the core ``ai-parrot`` distribution (FEAT-416); merged in
  below.

FEAT-416 (TASK-2152) packaging note: ``parrot.voice`` is split across two
installed distributions — this one (``ai-parrot-integrations``, this
file) and core ``ai-parrot`` (``parrot/voice/session.py``, no
``__init__.py`` there — a bare PEP 420 namespace directory). A package
name normally can't be split across distributions once ANY one of them
has a real ``__init__.py`` (whichever the import system finds first wins
*exclusively*, discarding the other's submodules entirely) — this file's
own convenience re-export below means it can't just delete its
``__init__.py`` to fix that the way the core side did. The classic,
still-fully-supported fix predating PEP 420 is ``pkgutil.extend_path``:
it patches ``__path__`` to merge in every other installed distribution's
matching ``parrot/voice/`` directory, so ``parrot.voice.session`` (core)
resolves correctly even though *this* file is the one Python actually
executes as the package's ``__init__``. See
``packages/ai-parrot/src/parrot/voice/`` (no ``__init__.py``) and TASK-2152's
Completion Note for the full analysis.
"""
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)

# Convenience re-export of the TTS synthesizer (FEAT-213).
# Full TTS surface is available via: from parrot.voice.tts import ...
from .tts import VoiceSynthesizer

__all__ = [
    "VoiceSynthesizer",
]
