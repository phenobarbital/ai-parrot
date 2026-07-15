---
type: Wiki Entity
title: RenderWarning
id: class:parrot_formdesigner.core.schema.RenderWarning
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Warning emitted when a renderer uses degraded fallback for a field type.
---

# RenderWarning

Defined in [`parrot_formdesigner.core.schema`](../summaries/mod:parrot_formdesigner.core.schema.md).

```python
class RenderWarning(BaseModel)
```

Warning emitted when a renderer uses degraded fallback for a field type.

Attributes:
    field_id: The ID of the field that triggered the fallback.
    field_type: The FieldType.value string (e.g. "signature").
    renderer: The renderer name ("html5" | "adaptive_card" | "pdf" |
              "xforms" | "jsonschema" | "telegram").
    reason: Human-readable explanation (e.g. "unsupported in PDF — rendered as placeholder").
