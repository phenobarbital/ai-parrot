---
type: Wiki Summary
title: parrot_formdesigner.renderers.audio
id: mod:parrot_formdesigner.renderers.audio
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AudioFormRenderer — Standalone audio form renderer for parrot-formdesigner.
relates_to:
- concept: class:parrot_formdesigner.renderers.audio.AudioFormRenderer
  rel: defines
- concept: func:parrot_formdesigner.renderers.audio.build_audio_synthesizer
  rel: defines
- concept: func:parrot_formdesigner.renderers.audio.classify_voice_mode
  rel: defines
- concept: func:parrot_formdesigner.renderers.audio.synthesize_with_fallback
  rel: defines
- concept: mod:parrot.voice.tts.models
  rel: references
- concept: mod:parrot.voice.tts.synthesizer
  rel: references
- concept: mod:parrot_formdesigner.audio.models
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.style
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
- concept: mod:parrot_formdesigner.renderers.base
  rel: references
---

# `parrot_formdesigner.renderers.audio`

AudioFormRenderer — Standalone audio form renderer for parrot-formdesigner.

Converts a FormSchema into an AudioFormManifest — a sequential list of
questions suitable for a voice-driven Q&A session over WebSocket.

The renderer is registered under the "audio" format key and is discoverable
at GET /api/v1/forms/{form_id}/render/audio.

Added by FEAT-224 (FormDesigner Audio Renderer).

## Classes

- **`AudioFormRenderer(AbstractFormRenderer)`** — Renders a FormSchema as an AudioFormManifest (sequential questions).

## Functions

- `def classify_voice_mode(field: FormField) -> VoiceMode` — Classify a FormField into a VoiceMode (FEAT-236).
- `def build_audio_synthesizer(config: AudioSessionConfig | None=None) -> 'VoiceSynthesizer | None'` — Build a VoiceSynthesizer preferring SuperTonic, else None (FEAT-236).
- `async def synthesize_with_fallback(text: str, *, config: AudioSessionConfig | None=None, language: str | None=None) -> bytes | None` — Synthesize ``text`` to audio bytes, SuperTonic→Google→text-only.
