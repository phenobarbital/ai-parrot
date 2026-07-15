---
type: Wiki Summary
title: parrot.voice.tts.backend
id: mod:parrot.voice.tts.backend
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract TTS Backend.
relates_to:
- concept: class:parrot.voice.tts.backend.AbstractTTSBackend
  rel: defines
- concept: mod:parrot.voice.tts.models
  rel: references
---

# `parrot.voice.tts.backend`

Abstract TTS Backend.

Defines the abstract base class for text-to-speech synthesis backends.
Concrete implementations (GoogleTTSBackend, and future ElevenLabs/OpenAI
backends) must implement the ``synthesize`` method.

Added by FEAT-213 (Telegram Voice Reply TTS Output).
Mirrors the structure of ``parrot.voice.transcriber.backend`` for symmetry.

## Classes

- **`AbstractTTSBackend(ABC)`** — Abstract base class for text-to-speech synthesis backends.
