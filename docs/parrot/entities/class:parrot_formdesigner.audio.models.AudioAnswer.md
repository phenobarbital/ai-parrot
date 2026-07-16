---
type: Wiki Entity
title: AudioAnswer
id: class:parrot_formdesigner.audio.models.AudioAnswer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: An answer to a single audio question.
---

# AudioAnswer

Defined in [`parrot_formdesigner.audio.models`](../summaries/mod:parrot_formdesigner.audio.models.md).

```python
class AudioAnswer(BaseModel)
```

An answer to a single audio question.

Attributes:
    field_id: The field_id this answer corresponds to.
    value: The answer text (either typed or transcribed).
    source: Origin of the answer — 'text' for keyboard input,
        'speech' for STT-transcribed audio, 'selection' for a UI
        selection on a PROMPT_SELECT question (FEAT-236).
    confidence: STT confidence score (0.0–1.0) when source='speech'.
    raw_transcript: Raw unprocessed transcript when source='speech'.
