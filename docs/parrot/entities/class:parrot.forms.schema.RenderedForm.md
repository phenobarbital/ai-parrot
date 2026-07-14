---
type: Wiki Entity
title: RenderedForm
id: class:parrot.forms.schema.RenderedForm
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Output of a form renderer.
---

# RenderedForm

Defined in [`parrot.forms.schema`](../summaries/mod:parrot.forms.schema.md).

```python
class RenderedForm(BaseModel)
```

Output of a form renderer.

Attributes:
    content: The rendered form content (varies by renderer).
    content_type: MIME type or format identifier for the content.
    style_output: Optional style-related output from the renderer.
    metadata: Renderer-specific metadata about the rendering process.
