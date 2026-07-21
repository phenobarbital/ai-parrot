---
type: Wiki Summary
title: parrot.voice.tts
id: mod:parrot.voice.tts
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: TTS (Text-to-Speech) Module.
relates_to:
- concept: mod:parrot.voice
  rel: references
- concept: mod:parrot.voice.models
  rel: references
---

# `parrot.voice.tts`

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
