---
type: Concept
title: register_renderer()
id: func:parrot_formdesigner.api.render.register_renderer
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Register (or overwrite) a renderer under ``format_key``.
---

# register_renderer

```python
def register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None
```

Register (or overwrite) a renderer under ``format_key``.

Args:
    format_key: The path-param value used in
        ``GET /api/v1/forms/{form_id}/render/{format}``.
    renderer: An ``AbstractFormRenderer`` instance.
