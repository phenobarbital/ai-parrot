---
type: Wiki Entity
title: AudioFieldRenderer
id: class:parrot_formdesigner.renderers.fields.audio.AudioFieldRenderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTML5 field renderer for FieldType.AUDIO fields.
---

# AudioFieldRenderer

Defined in [`parrot_formdesigner.renderers.fields.audio`](../summaries/mod:parrot_formdesigner.renderers.fields.audio.md).

```python
class AudioFieldRenderer
```

HTML5 field renderer for FieldType.AUDIO fields.

Produces a self-contained HTML snippet with:
- A label element for the field.
- A record button (start/stop toggle).
- A visual waveform indicator.
- A hidden <input> that stores the transcribed text.
- Inline JavaScript using the MediaRecorder API.

Implements the FieldRenderer protocol so it can be registered in
HTML5Renderer._registry.

Example::

    renderer = AudioFieldRenderer()
    html_snippet = await renderer.render(field, locale="en")

## Methods

- `async def render(self, field: FormField, *, locale: str='en', prefilled: Any=None, error: str | None=None) -> str` — Render the audio field as an HTML5 snippet.
