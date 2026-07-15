---
type: Wiki Entity
title: FieldRenderer
id: class:parrot_formdesigner.renderers.base.FieldRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-target field renderer. One concrete impl per (FieldType, output target).
---

# FieldRenderer

Defined in [`parrot_formdesigner.renderers.base`](../summaries/mod:parrot_formdesigner.renderers.base.md).

```python
class FieldRenderer(Protocol)
```

Per-target field renderer. One concrete impl per (FieldType, output target).

The render() signature uses keyword-only args so callers can pass optional
context without breaking positional compatibility. Return type is Any
because each output target uses a different representation (str for HTML5,
dict for Adaptive Card/JSON Schema, bytes for PDF, etc.).

## Methods

- `async def render(self, field: FormField, *, locale: str='en', prefilled: Any=None, error: str | None=None) -> Any`
