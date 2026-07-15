---
type: Wiki Entity
title: AudioQuestion
id: class:parrot_formdesigner.audio.models.AudioQuestion
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A single question in the audio form session.
---

# AudioQuestion

Defined in [`parrot_formdesigner.audio.models`](../summaries/mod:parrot_formdesigner.audio.models.md).

```python
class AudioQuestion(BaseModel)
```

A single question in the audio form session.

Attributes:
    index: Zero-based position in the sequential question list.
    field_id: The FormField.field_id this question maps to.
    field_type: The FieldType value string (e.g. 'text', 'select').
    label: Resolved question text shown/spoken to the user.
    description: Optional extended description or help text.
    required: Whether an answer is mandatory.
    audio_prompt: Pre-synthesized TTS audio bytes, or None if not
        yet synthesized.
    constraints: Optional validation constraints dict.
    options: Option list for SELECT/MULTI_SELECT fields, each entry
        has at least 'value' and 'label' keys.
    voice_mode: The VoiceMode taxonomy classification for this
        question (FEAT-236).
    render_mode: Client-facing render hint derived from voice_mode —
        "voice" (speak + answer), "select" (UI selection), or
        "visual" (single-field visual fallback).
    sensitive: When True, the client must mute TTS read-back of the
        value (e.g. password fields).
    fallback_html: Pre-rendered single-field HTML for VISUAL_FALLBACK
        questions, or None.
