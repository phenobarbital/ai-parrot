---
type: Wiki Entity
title: InvokeError
id: class:parrot.exceptions.InvokeError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when an ``invoke()`` call fails.
relates_to:
- concept: class:parrot.exceptions.ParrotError
  rel: extends
---

# InvokeError

Defined in [`parrot.exceptions`](../summaries/mod:parrot.exceptions.md).

```python
class InvokeError(ParrotError)
```

Raised when an ``invoke()`` call fails.

Wraps provider-level exceptions so callers get a consistent error type
regardless of which LLM backend was used.

Args:
    message: Human-readable error description.
    *args: Forwarded to :class:`ParrotError`.
    original: The original provider exception, preserved for debugging.
    **kwargs: Forwarded to :class:`ParrotError`.

Attributes:
    original: The original exception that caused this error, or ``None``.
