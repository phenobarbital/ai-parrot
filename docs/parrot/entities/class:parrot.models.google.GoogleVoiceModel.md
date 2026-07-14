---
type: Wiki Entity
title: GoogleVoiceModel
id: class:parrot.models.google.GoogleVoiceModel
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Available models for Gemini Live API.
---

# GoogleVoiceModel

Defined in [`parrot.models.google`](../summaries/mod:parrot.models.google.md).

```python
class GoogleVoiceModel(str, Enum)
```

Available models for Gemini Live API.

Native Audio models support bidirectional voice streaming.
See: https://ai.google.dev/gemini-api/docs/live

## Methods

- `def all_models(cls) -> List[str]` — Get all available model strings.
