---
type: Wiki Entity
title: ForwardResult
id: class:parrot_formdesigner.services.forwarder.ForwardResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result of a submission forwarding attempt.
---

# ForwardResult

Defined in [`parrot_formdesigner.services.forwarder`](../summaries/mod:parrot_formdesigner.services.forwarder.md).

```python
class ForwardResult(BaseModel)
```

Result of a submission forwarding attempt.

Attributes:
    success: ``True`` when the remote endpoint returned a 2xx/3xx response.
    status_code: HTTP status code received from the remote endpoint (if any).
    error: Human-readable error message when ``success`` is ``False``.
