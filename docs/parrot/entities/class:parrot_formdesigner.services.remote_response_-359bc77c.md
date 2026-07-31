---
type: Wiki Entity
title: RemoteResponseResolver
id: class:parrot_formdesigner.services.remote_response_resolver.RemoteResponseResolver
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Resolve REMOTE_RESPONSE fields by calling an external API.
---

# RemoteResponseResolver

Defined in [`parrot_formdesigner.services.remote_response_resolver`](../summaries/mod:parrot_formdesigner.services.remote_response_resolver.md).

```python
class RemoteResponseResolver
```

Resolve REMOTE_RESPONSE fields by calling an external API.

Mirrors ``SubmissionForwarder`` aiohttp + auth pattern. Every call hits
the endpoint — no memoisation. Callers must ensure endpoint idempotency
if needed.

Attributes:
    DEFAULT_TIMEOUT: Default request timeout in seconds (30).
    timeout: Configured timeout for this resolver instance.

Args:
    timeout: Request timeout in seconds. Defaults to ``DEFAULT_TIMEOUT``.

## Methods

- `async def resolve(self, spec: RemoteResponseSpec, content: Any, *, auth_context: AuthContext | None=None) -> RemoteResponseResult` — Call the external API and return its response as the field value.
