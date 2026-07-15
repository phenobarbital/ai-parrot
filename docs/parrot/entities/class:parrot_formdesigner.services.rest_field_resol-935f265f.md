---
type: Wiki Entity
title: RestCallbackOutput
id: class:parrot_formdesigner.services.rest_field_resolver.RestCallbackOutput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return value from a registered callback coroutine.
---

# RestCallbackOutput

Defined in [`parrot_formdesigner.services.rest_field_resolver`](../summaries/mod:parrot_formdesigner.services.rest_field_resolver.md).

```python
class RestCallbackOutput(BaseModel)
```

Return value from a registered callback coroutine.

Attributes:
    success: Whether the callback completed successfully.
    value: Extracted or computed answer value.
    status_code: Optional synthetic HTTP status code for logging.
    error: Human-readable error message on failure.
