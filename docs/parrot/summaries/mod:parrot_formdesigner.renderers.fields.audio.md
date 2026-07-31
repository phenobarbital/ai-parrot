---
type: Wiki Summary
title: parrot_formdesigner.renderers.fields.audio
id: mod:parrot_formdesigner.renderers.fields.audio
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AudioFieldRenderer — HTML5 field renderer for FieldType.AUDIO.
relates_to:
- concept: class:parrot_formdesigner.renderers.fields.audio.AudioFieldRenderer
  rel: defines
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
---

# `parrot_formdesigner.renderers.fields.audio`

AudioFieldRenderer — HTML5 field renderer for FieldType.AUDIO.

Renders a FieldType.AUDIO field as a record button + hidden input + inline
JavaScript using the MediaRecorder API. The recording button controls
start/stop, the waveform indicator provides visual feedback, and the hidden
<input> stores the transcribed text (populated via the audio WebSocket or
client-side transcription).

This renderer implements the FieldRenderer protocol and is registered in
HTML5Renderer._build_registry() for FieldType.AUDIO.

Added by FEAT-224 (FormDesigner Audio Renderer).

## Classes

- **`AudioFieldRenderer`** — HTML5 field renderer for FieldType.AUDIO fields.
