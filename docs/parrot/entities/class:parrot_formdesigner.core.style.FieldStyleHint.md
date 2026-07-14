---
type: Wiki Entity
title: FieldStyleHint
id: class:parrot_formdesigner.core.style.FieldStyleHint
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-field style customization hints.
---

# FieldStyleHint

Defined in [`parrot_formdesigner.core.style`](../summaries/mod:parrot_formdesigner.core.style.md).

```python
class FieldStyleHint(BaseModel)
```

Per-field style customization hints.

Attributes:
    size: Size hint controlling how much horizontal space the field occupies.
    order: Override the field's display order within its section.
    css_class: Additional CSS class(es) for HTML5 rendering.
    variant: Renderer-specific variant identifier (e.g., "outlined", "filled").
