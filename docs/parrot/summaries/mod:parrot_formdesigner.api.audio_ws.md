---
type: Wiki Summary
title: parrot_formdesigner.api.audio_ws
id: mod:parrot_formdesigner.api.audio_ws
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AudioFormWSHandler — WebSocket handler for interactive audio form sessions.
relates_to:
- concept: class:parrot_formdesigner.api.audio_ws.AudioFormWSHandler
  rel: defines
- concept: mod:parrot.core.ws_auth
  rel: references
- concept: mod:parrot.voice.transcriber.faster_whisper_backend
  rel: references
- concept: mod:parrot.voice.tts.models
  rel: references
- concept: mod:parrot.voice.tts.synthesizer
  rel: references
- concept: mod:parrot_formdesigner.audio.models
  rel: references
- concept: mod:parrot_formdesigner.core.options
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
- concept: mod:parrot_formdesigner.renderers.audio
  rel: references
- concept: mod:parrot_formdesigner.renderers.html5
  rel: references
- concept: mod:parrot_formdesigner.services.registry
  rel: references
- concept: mod:parrot_formdesigner.services.submissions
  rel: references
- concept: mod:parrot_formdesigner.services.validators
  rel: references
---

# `parrot_formdesigner.api.audio_ws`

AudioFormWSHandler — WebSocket handler for interactive audio form sessions.

Manages a stateful audio Q&A session over WebSocket: one question at a time,
text or audio answers, TTS delivery, STT transcription, validation, and
final form submission.

WebSocket protocol (see spec §2 for full message definitions):
- Client sends JSON messages with a "type" field.
- Binary frames are treated as audio data for STT transcription.
- Server responds with JSON messages.

Authentication: JWT token extracted from Sec-WebSocket-Protocol header or
from the first "auth" type message. Unauthenticated connections receive an
error and are closed.

Added by FEAT-224 (FormDesigner Audio Renderer).

## Classes

- **`AudioFormWSHandler`** — WebSocket handler for interactive audio form sessions.
