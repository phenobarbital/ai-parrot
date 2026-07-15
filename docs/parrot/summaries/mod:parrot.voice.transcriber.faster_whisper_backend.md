---
type: Wiki Summary
title: parrot.voice.transcriber.faster_whisper_backend
id: mod:parrot.voice.transcriber.faster_whisper_backend
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Faster Whisper Backend for Voice Transcription.
relates_to:
- concept: class:parrot.voice.transcriber.faster_whisper_backend.FasterWhisperBackend
  rel: defines
- concept: mod:parrot.voice.transcriber.backend
  rel: references
- concept: mod:parrot.voice.transcriber.models
  rel: references
---

# `parrot.voice.transcriber.faster_whisper_backend`

Faster Whisper Backend for Voice Transcription.

Local GPU-accelerated transcription backend using the faster-whisper library.
This is the default backend for voice transcription, offering low latency
and no API costs.

Originally part of FEAT-008 (MS Teams Voice Note Support),
refactored to shared location for FEAT-039.

## Classes

- **`FasterWhisperBackend(AbstractTranscriberBackend)`** — Local GPU-accelerated transcription using Faster Whisper.
