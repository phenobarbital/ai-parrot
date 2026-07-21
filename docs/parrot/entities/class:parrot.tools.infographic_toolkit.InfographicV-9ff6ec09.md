---
type: Wiki Entity
title: InfographicValidationError
id: class:parrot.tools.infographic_toolkit.InfographicValidationError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Structured error raised by the validation pipeline.
---

# InfographicValidationError

Defined in [`parrot.tools.infographic_toolkit`](../summaries/mod:parrot.tools.infographic_toolkit.md).

```python
class InfographicValidationError(Exception)
```

Structured error raised by the validation pipeline.

All errors carry a stable ``code`` (for client routing) and a ``detail``
dict (for structured logging and user display).

Valid codes::

    TEMPLATE_UNKNOWN
    SLOT_MISSING
    SLOT_TYPE_MISMATCH
    SLOT_ITEM_COUNT_INVALID
    EXTRA_BLOCKS
    DATA_VAR_MISSING
    DATA_VAR_EMPTY
    THEME_INVALID
    ENHANCE_OUTPUT_INVALID
    TEMPLATE_ENGINE_UNSET    # render_template: no templates configured
    TEMPLATE_RENDER_ERROR    # render_template: Jinja render failure
