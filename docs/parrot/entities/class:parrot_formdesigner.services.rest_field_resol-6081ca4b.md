---
type: Wiki Entity
title: RestFieldResolver
id: class:parrot_formdesigner.services.rest_field_resolver.RestFieldResolver
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Dispatch FieldType.REST field uploads by mode.
---

# RestFieldResolver

Defined in [`parrot_formdesigner.services.rest_field_resolver`](../summaries/mod:parrot_formdesigner.services.rest_field_resolver.md).

```python
class RestFieldResolver
```

Dispatch FieldType.REST field uploads by mode.

Supports three modes:
- ``remote``: POST/GET to an absolute external URL.
- ``internal``: POST/GET to a relative path on the running server.
- ``callback``: Invoke a pre-registered Python coroutine.

Mirrors the ``RemoteResponseResolver`` aiohttp pattern. **Never raises**
from ``resolve()`` — all errors flow into ``RestFieldResult``.

Args:
    timeout: Default HTTP timeout in seconds. Defaults to 30.
    internal_base_url: Explicit base URL for ``internal`` mode
        (e.g. ``"http://localhost:8080"``). Takes priority over the
        ``PARROT_INTERNAL_BASE_URL`` env var and request-host fallback.

## Methods

- `async def resolve(self, spec: RemoteRestFieldSpec | InternalRestFieldSpec | CallbackRestFieldSpec, payload: RestCallbackInput, *, auth_context: AuthContext | None=None, tenant: str | None=None, request_host: str | None=None) -> RestFieldResult` — Dispatch by ``spec.mode`` and return the result.
