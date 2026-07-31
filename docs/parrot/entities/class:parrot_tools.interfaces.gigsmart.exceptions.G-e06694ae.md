---
type: Wiki Entity
title: GigSmartError
id: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Base exception for all GigSmart API errors.
---

# GigSmartError

Defined in [`parrot_tools.interfaces.gigsmart.exceptions`](../summaries/mod:parrot_tools.interfaces.gigsmart.exceptions.md).

```python
class GigSmartError(Exception)
```

Base exception for all GigSmart API errors.

Args:
    message: Human-readable error description.
    status_code: HTTP status code associated with the error, if any.
