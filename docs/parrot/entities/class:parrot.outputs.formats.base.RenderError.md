---
type: Wiki Entity
title: RenderError
id: class:parrot.outputs.formats.base.RenderError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Structured error information from rendering.
---

# RenderError

Defined in [`parrot.outputs.formats.base`](../summaries/mod:parrot.outputs.formats.base.md).

```python
class RenderError
```

Structured error information from rendering.

Attributes:
    message: Human-readable error message
    error_type: Type of error (e.g., 'json_parse', 'validation', 'execution')
    raw_output: The original output that failed to render
    details: Additional error details (stack trace, position, etc.)
