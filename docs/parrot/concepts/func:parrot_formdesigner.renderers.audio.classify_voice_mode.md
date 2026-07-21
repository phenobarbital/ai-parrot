---
type: Concept
title: classify_voice_mode()
id: func:parrot_formdesigner.renderers.audio.classify_voice_mode
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Classify a FormField into a VoiceMode (FEAT-236).
---

# classify_voice_mode

```python
def classify_voice_mode(field: FormField) -> VoiceMode
```

Classify a FormField into a VoiceMode (FEAT-236).

A per-field override in ``field.meta["voice_mode"]`` (case-insensitive
match against the VoiceMode values) wins over the default FieldType table.
An invalid override logs a warning and falls back to the default.

Args:
    field: The FormField to classify.

Returns:
    The VoiceMode for this field.
