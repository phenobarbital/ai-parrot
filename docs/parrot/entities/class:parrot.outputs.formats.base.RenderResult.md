---
type: Wiki Entity
title: RenderResult
id: class:parrot.outputs.formats.base.RenderResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Structured result from rendering operation.
---

# RenderResult

Defined in [`parrot.outputs.formats.base`](../summaries/mod:parrot.outputs.formats.base.md).

```python
class RenderResult
```

Structured result from rendering operation.

This provides more detailed information about the rendering outcome,
including whether it succeeded and any error information.

Attributes:
    success: Whether rendering succeeded
    content: The rendered content (may be partial on error)
    wrapped_content: Optional wrapped version (e.g., HTML)
    error: Error information if rendering failed
