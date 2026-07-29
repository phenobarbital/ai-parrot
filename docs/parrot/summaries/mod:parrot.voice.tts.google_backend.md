---
type: Wiki Summary
title: parrot.voice.tts.google_backend
id: mod:parrot.voice.tts.google_backend
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Google TTS Backend.
relates_to:
- concept: class:parrot.voice.tts.google_backend.GoogleTTSBackend
  rel: defines
- concept: mod:parrot.clients.google
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.voice.tts.backend
  rel: references
- concept: mod:parrot.voice.tts.models
  rel: references
---

# `parrot.voice.tts.google_backend`

Google TTS Backend.

Implements AbstractTTSBackend using GoogleGenAIClient.generate_speech.
This is the default backend for VoiceSynthesizer.

The audio returned by ``generate_speech`` is raw PCM data (Gemini TTS
produces 24kHz mono 16-bit PCM). The actual container format—and therefore
the ``mime_format`` field in the returned ``SynthesisResult``—is whatever
was requested via the ``mime_format`` argument; note that Telegram voice
notes prefer OGG/Opus, so container conversion is handled by the caller
(TASK-1409 / Telegram wrapper).

Added by FEAT-213 (Telegram Voice Reply TTS Output).

## Classes

- **`GoogleTTSBackend(AbstractTTSBackend)`** — TTS backend that wraps ``GoogleGenAIClient.generate_speech``.
