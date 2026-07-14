---
type: Wiki Entity
title: ParrotError
id: class:parrot.exceptions.ParrotError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for Parrot exceptions.
---

# ParrotError

Defined in [`parrot.exceptions`](../summaries/mod:parrot.exceptions.md).

```python
class ParrotError(Exception)
```

Base class for Parrot exceptions.

Args:
    message: The error message. If the object has a ``.message``
        attribute, that attribute value is used as the message string.
    *args: Ignored positional arguments (for compatibility with
        ``Exception`` call conventions).
    **kwargs: Optional keyword arguments. ``stacktrace`` is extracted and
        stored on ``self.stacktrace``; all kwargs are stored on
        ``self.args`` for backward compatibility with the Cython original.

## Methods

- `def get(self) -> str` — Return the message of the exception.
