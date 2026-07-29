---
type: Wiki Entity
title: AudioFormManifest
id: class:parrot_formdesigner.audio.models.AudioFormManifest
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Session manifest returned by AudioFormRenderer.render().
---

# AudioFormManifest

Defined in [`parrot_formdesigner.audio.models`](../summaries/mod:parrot_formdesigner.audio.models.md).

```python
class AudioFormManifest(BaseModel)
```

Session manifest returned by AudioFormRenderer.render().

Describes the sequential list of questions and the WebSocket endpoint
for the interactive audio session.

Attributes:
    form_id: The form identifier.
    title: Human-readable form title.
    total_questions: Number of questions in the audio session.
    questions: Ordered list of audio questions.
    ws_endpoint: WebSocket URL template for the interactive session.
    locale: Resolved locale used for this manifest.
