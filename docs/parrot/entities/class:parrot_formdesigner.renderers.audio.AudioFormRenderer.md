---
type: Wiki Entity
title: AudioFormRenderer
id: class:parrot_formdesigner.renderers.audio.AudioFormRenderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Renders a FormSchema as an AudioFormManifest (sequential questions).
---

# AudioFormRenderer

Defined in [`parrot_formdesigner.renderers.audio`](../summaries/mod:parrot_formdesigner.renderers.audio.md).

```python
class AudioFormRenderer(AbstractFormRenderer)
```

Renders a FormSchema as an AudioFormManifest (sequential questions).

The manifest is returned as `RenderedForm.content` (a dict) with
`content_type="application/json"`. Optionally pre-synthesizes TTS audio
for each question when a `VoiceSynthesizer` is provided.

The renderer is registered under the ``"audio"`` format key by
``_seed_default_renderers()`` in ``api/render.py``.

Args:
    synthesizer: Optional VoiceSynthesizer. When provided, each question
        will have its label synthesized to bytes stored in
        ``AudioQuestion.audio_prompt``.

Example::

    renderer = AudioFormRenderer()
    result = await renderer.render(form_schema, locale="en")
    manifest = result.content  # dict with form_id, questions, ws_endpoint, ...

## Methods

- `def split_into_questions(self, form: FormSchema, *, locale: str='en') -> list[AudioQuestion]` — Flatten a FormSchema into a sequential list of AudioQuestion objects.
- `async def render(self, form: FormSchema, style: StyleSchema | None=None, *, locale: str='en', prefilled: dict[str, Any] | None=None, errors: dict[str, str] | None=None) -> RenderedForm` — Render a FormSchema into an AudioFormManifest.
