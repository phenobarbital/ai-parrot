---
type: Wiki Summary
title: parrot.voice.models
id: mod:parrot.voice.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Voice Module Data Models
relates_to:
- concept: class:parrot.voice.models.AudioFormat
  rel: defines
- concept: class:parrot.voice.models.SessionState
  rel: defines
- concept: class:parrot.voice.models.VoiceChunk
  rel: defines
- concept: class:parrot.voice.models.VoiceConfig
  rel: defines
- concept: class:parrot.voice.models.VoiceMessage
  rel: defines
- concept: class:parrot.voice.models.VoiceProvider
  rel: defines
- concept: class:parrot.voice.models.VoiceResponse
  rel: defines
---

# `parrot.voice.models`

Voice Module Data Models

Defines the data structures for voice interactions, including
audio chunks, voice messages, and response formats.

## Classes

- **`AudioFormat(Enum)`** — Supported audio formats for voice streaming.
- **`VoiceProvider(Enum)`** — Supported voice providers.
- **`SessionState(Enum)`** — Voice session states.
- **`VoiceChunk`** — Represents a chunk of audio data in a voice stream.
- **`VoiceMessage`** — Represents a complete voice message in a conversation.
- **`VoiceResponse`** — Response from a voice interaction.
- **`VoiceConfig`** — Configuration for voice sessions.
