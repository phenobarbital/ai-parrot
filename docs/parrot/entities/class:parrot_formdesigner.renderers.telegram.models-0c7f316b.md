---
type: Wiki Entity
title: TelegramFormPayload
id: class:parrot_formdesigner.renderers.telegram.models.TelegramFormPayload
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Output of TelegramRenderer.render(), stored in RenderedForm.content.
---

# TelegramFormPayload

Defined in [`parrot_formdesigner.renderers.telegram.models`](../summaries/mod:parrot_formdesigner.renderers.telegram.models.md).

```python
class TelegramFormPayload(BaseModel)
```

Output of TelegramRenderer.render(), stored in RenderedForm.content.

Attributes:
    mode: The rendering mode selected.
    form_id: Form identifier.
    form_title: Human-readable form title.
    steps: List of inline form steps (inline mode only).
    webapp_url: URL to the WebApp page (webapp mode only).
    summary_text: Pre-submit summary template.
    total_fields: Total number of renderable fields.
