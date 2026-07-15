---
type: Wiki Entity
title: GigSmartRateLimitError
id: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartRateLimitError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Rate limit exceeded (HTTP 429 / ``RATE_LIMITED`` extension code).
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartError
  rel: extends
---

# GigSmartRateLimitError

Defined in [`parrot_tools.interfaces.gigsmart.exceptions`](../summaries/mod:parrot_tools.interfaces.gigsmart.exceptions.md).

```python
class GigSmartRateLimitError(GigSmartError)
```

Rate limit exceeded (HTTP 429 / ``RATE_LIMITED`` extension code).

Args:
    message: Human-readable error description.
    retry_after: Seconds to wait before retrying, derived from the
        ``Retry-After`` response header. Defaults to 60 when the header
        is absent.
