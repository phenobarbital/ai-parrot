---
type: Wiki Summary
title: parrot.voice.transcriber.models
id: mod:parrot.voice.transcriber.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Voice Transcription Data Models.
relates_to:
- concept: class:parrot.voice.transcriber.models.TranscriberBackend
  rel: defines
- concept: class:parrot.voice.transcriber.models.TranscriptionResult
  rel: defines
- concept: class:parrot.voice.transcriber.models.VoiceTranscriberConfig
  rel: defines
---

# `parrot.voice.transcriber.models`

Voice Transcription Data Models.

Pydantic models for voice transcription configuration and results.
These models are shared across all integrations that support voice input.

Originally part of FEAT-008 (MS Teams Voice Note Support),
refactored to shared location for FEAT-039.

## Classes

- **`TranscriberBackend(str, Enum)`** — Available transcription backends.
- **`VoiceTranscriberConfig(BaseModel)`** — Configuration for voice transcription.
- **`TranscriptionResult(BaseModel)`** — Result of voice transcription.
