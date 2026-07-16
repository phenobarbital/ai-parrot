---
type: Wiki Summary
title: parrot.voice.transcriber.transcriber
id: mod:parrot.voice.transcriber.transcriber
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Voice Transcriber Service.
relates_to:
- concept: class:parrot.voice.transcriber.transcriber.VoiceTranscriber
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.voice.transcriber.backend
  rel: references
- concept: mod:parrot.voice.transcriber.faster_whisper_backend
  rel: references
- concept: mod:parrot.voice.transcriber.models
  rel: references
- concept: mod:parrot.voice.transcriber.moonshine_backend
  rel: references
- concept: mod:parrot.voice.transcriber.openai_backend
  rel: references
---

# `parrot.voice.transcriber.transcriber`

Voice Transcriber Service.

Main service that orchestrates voice transcription. Selects the appropriate
backend based on configuration, handles audio downloads from URLs,
manages temp files, and provides the unified interface used by
integration wrappers (MS Teams, Telegram, etc.).

Originally part of FEAT-008 (MS Teams Voice Note Support),
refactored to shared location for FEAT-039.

## Classes

- **`VoiceTranscriber`** — Voice transcription service.
