---
type: Wiki Summary
title: parrot.voice.tts.models
id: mod:parrot.voice.tts.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: TTS Data Models.
relates_to:
- concept: class:parrot.voice.tts.models.SynthesisResult
  rel: defines
- concept: class:parrot.voice.tts.models.TTSConfig
  rel: defines
---

# `parrot.voice.tts.models`

TTS Data Models.

Pydantic models for text-to-speech configuration and synthesis results.
These models are shared across all TTS backends (Google, ElevenLabs, etc.)
and the VoiceSynthesizer service.

Added by FEAT-213 (Telegram Voice Reply TTS Output).
Mirrors the structure of ``parrot.voice.transcriber.models`` for symmetry.

## Classes

- **`TTSConfig(BaseModel)`** — Configuration for text-to-speech synthesis.
- **`SynthesisResult(BaseModel)`** — Result of a text-to-speech synthesis call.
