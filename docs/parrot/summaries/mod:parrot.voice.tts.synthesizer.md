---
type: Wiki Summary
title: parrot.voice.tts.synthesizer
id: mod:parrot.voice.tts.synthesizer
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Voice Synthesizer Service.
relates_to:
- concept: class:parrot.voice.tts.synthesizer.VoiceSynthesizer
  rel: defines
- concept: mod:parrot.voice.tts.backend
  rel: references
- concept: mod:parrot.voice.tts.google_backend
  rel: references
- concept: mod:parrot.voice.tts.models
  rel: references
- concept: mod:parrot.voice.tts.supertonic_inference
  rel: references
---

# `parrot.voice.tts.synthesizer`

Voice Synthesizer Service.

Main service that orchestrates text-to-speech synthesis. Selects the
appropriate backend based on configuration, manages the backend lifecycle,
and provides a unified ``synthesize(text)`` interface used by integration
wrappers (Telegram, etc.).

Mirrors the structure of ``parrot.voice.transcriber.transcriber.VoiceTranscriber``.
Added by FEAT-213 (Telegram Voice Reply TTS Output).

## Classes

- **`VoiceSynthesizer`** — Text-to-speech synthesis service.
