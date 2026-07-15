---
type: Wiki Entity
title: InteractiveValidationError
id: class:parrot.tools.interactive_toolkit.InteractiveValidationError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Structured error raised by the interactive render pipeline.
---

# InteractiveValidationError

Defined in [`parrot.tools.interactive_toolkit`](../summaries/mod:parrot.tools.interactive_toolkit.md).

```python
class InteractiveValidationError(Exception)
```

Structured error raised by the interactive render pipeline.

Carries a stable ``code`` (for client routing) and a ``detail`` dict.

Valid codes::

    TEMPLATE_UNKNOWN
    LIBRARY_UNKNOWN
    LIBRARY_NOT_ALLOWED
    ENHANCE_BRIEF_MISSING
    ENHANCE_OUTPUT_INVALID
