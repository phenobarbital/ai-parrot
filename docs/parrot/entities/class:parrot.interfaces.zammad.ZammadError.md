---
type: Wiki Entity
title: ZammadError
id: class:parrot.interfaces.zammad.ZammadError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base exception for Zammad REST API errors.
---

# ZammadError

Defined in [`parrot.interfaces.zammad`](../summaries/mod:parrot.interfaces.zammad.md).

```python
class ZammadError(Exception)
```

Base exception for Zammad REST API errors.

Attributes:
    status_code: HTTP status code returned by Zammad, if any.
