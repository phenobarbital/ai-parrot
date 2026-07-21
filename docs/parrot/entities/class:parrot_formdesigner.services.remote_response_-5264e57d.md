---
type: Wiki Entity
title: RemoteResponseResult
id: class:parrot_formdesigner.services.remote_response_resolver.RemoteResponseResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of a ``RemoteResponseResolver.resolve()`` call.
---

# RemoteResponseResult

Defined in [`parrot_formdesigner.services.remote_response_resolver`](../summaries/mod:parrot_formdesigner.services.remote_response_resolver.md).

```python
class RemoteResponseResult(BaseModel)
```

Result of a ``RemoteResponseResolver.resolve()`` call.

Attributes:
    success: True when the endpoint returned a 2xx response.
    value: Parsed response value (JSON) from the endpoint.
    status_code: HTTP status code received from the endpoint (if any).
    error: Human-readable error message when ``success`` is False.
