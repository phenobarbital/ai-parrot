---
type: Wiki Summary
title: parrot.voice.transcriber.backend
id: mod:parrot.voice.transcriber.backend
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract Transcriber Backend.
relates_to:
- concept: class:parrot.voice.transcriber.backend.AbstractTranscriberBackend
  rel: defines
- concept: mod:parrot.voice.transcriber.models
  rel: references
---

# `parrot.voice.transcriber.backend`

Abstract Transcriber Backend.

Defines the abstract base class for voice transcription backends.
Both FasterWhisperBackend and OpenAIWhisperBackend implement this interface,
allowing the VoiceTranscriber service to work with either backend interchangeably.

Originally part of FEAT-008 (MS Teams Voice Note Support),
refactored to shared location for FEAT-039.

## Classes

- **`AbstractTranscriberBackend(ABC)`** — Abstract base class for transcription backends.
