---
type: Wiki Entity
title: RenderedForm
id: class:parrot_formdesigner.core.schema.RenderedForm
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Output of a form renderer.
---

# RenderedForm

Defined in [`parrot_formdesigner.core.schema`](../summaries/mod:parrot_formdesigner.core.schema.md).

```python
class RenderedForm(BaseModel)
```

Output of a form renderer.

Attributes:
    content: The rendered form content (varies by renderer).
    content_type: MIME type or format identifier for the content.
    style_output: Optional style-related output from the renderer.
    metadata: Renderer-specific metadata about the rendering process.
    warnings: Degraded-rendering warnings. Empty list when all fields
        rendered natively. One entry per (field_id, renderer) pair that
        used FallbackRenderer.
