---
type: Wiki Summary
title: parrot.voice.transcriber.openai_backend
id: mod:parrot.voice.transcriber.openai_backend
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: OpenAI Whisper Backend for Voice Transcription.
relates_to:
- concept: class:parrot.voice.transcriber.openai_backend.OpenAIWhisperBackend
  rel: defines
- concept: mod:parrot.voice.transcriber.backend
  rel: references
- concept: mod:parrot.voice.transcriber.models
  rel: references
---

# `parrot.voice.transcriber.openai_backend`

OpenAI Whisper Backend for Voice Transcription.

Cloud-based transcription backend using OpenAI's Whisper API.
This provides an alternative to local GPU transcription for environments
without GPU access or for simpler deployment.

Originally part of FEAT-008 (MS Teams Voice Note Support),
refactored to shared location for FEAT-039.

## Classes

- **`OpenAIWhisperBackend(AbstractTranscriberBackend)`** — Cloud-based transcription using OpenAI Whisper API.
