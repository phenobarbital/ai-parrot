---
type: Wiki Entity
title: RemoteResponseSpec
id: class:parrot_formdesigner.services.remote_response_resolver.RemoteResponseSpec
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for a REMOTE_RESPONSE field embedded in ``FormField.meta``.
---

# RemoteResponseSpec

Defined in [`parrot_formdesigner.services.remote_response_resolver`](../summaries/mod:parrot_formdesigner.services.remote_response_resolver.md).

```python
class RemoteResponseSpec(BaseModel)
```

Configuration for a REMOTE_RESPONSE field embedded in ``FormField.meta``.

Attributes:
    endpoint: URL of the external API to call.
    http_method: HTTP verb to use. Defaults to "POST".
    content_field: Other field ID whose value is sent as request body
        (resolved by the caller before invoking the resolver).
    prompt: Optional prompt string sent alongside content.
    auth_ref: Reference key into the ``AuthContext`` credentials store.
    timeout_seconds: Per-request timeout in seconds. Defaults to 30.
    response_schema: Optional JSON Schema dict to validate the API response.
        Validation is informational — the resolver never rejects a valid 2xx.
