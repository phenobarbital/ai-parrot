---
type: Wiki Summary
title: parrot_formdesigner.audio.models
id: mod:parrot_formdesigner.audio.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Audio form session data models for parrot-formdesigner.
relates_to:
- concept: class:parrot_formdesigner.audio.models.AudioAnswer
  rel: defines
- concept: class:parrot_formdesigner.audio.models.AudioFormManifest
  rel: defines
- concept: class:parrot_formdesigner.audio.models.AudioQuestion
  rel: defines
- concept: class:parrot_formdesigner.audio.models.AudioSessionConfig
  rel: defines
- concept: class:parrot_formdesigner.audio.models.AudioSessionState
  rel: defines
- concept: class:parrot_formdesigner.audio.models.VoiceMode
  rel: defines
---

# `parrot_formdesigner.audio.models`

Audio form session data models for parrot-formdesigner.

Pydantic models shared by the audio renderer and WebSocket handler.
These models define the data contract for an audio form session.

Added by FEAT-224 (FormDesigner Audio Renderer).

## Classes

- **`VoiceMode(str, Enum)`** — How a question participates in the audio form flow.
- **`AudioSessionConfig(BaseModel)`** — Configuration for an audio form session.
- **`AudioQuestion(BaseModel)`** — A single question in the audio form session.
- **`AudioFormManifest(BaseModel)`** — Session manifest returned by AudioFormRenderer.render().
- **`AudioAnswer(BaseModel)`** — An answer to a single audio question.
- **`AudioSessionState(BaseModel)`** — Server-side state for an active audio form session.
