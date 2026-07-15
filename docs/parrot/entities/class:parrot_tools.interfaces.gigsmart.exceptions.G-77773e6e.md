---
type: Wiki Entity
title: GigSmartTransportError
id: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartTransportError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Network or server-side transport failure.
relates_to:
- concept: class:parrot_tools.interfaces.gigsmart.exceptions.GigSmartError
  rel: extends
---

# GigSmartTransportError

Defined in [`parrot_tools.interfaces.gigsmart.exceptions`](../summaries/mod:parrot_tools.interfaces.gigsmart.exceptions.md).

```python
class GigSmartTransportError(GigSmartError)
```

Network or server-side transport failure.

Raised on HTTP 5xx responses and unrecoverable network errors.
This class of error is retryable with exponential backoff.
