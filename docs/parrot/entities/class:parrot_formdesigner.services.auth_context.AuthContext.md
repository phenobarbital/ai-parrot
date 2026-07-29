---
type: Wiki Entity
title: AuthContext
id: class:parrot_formdesigner.services.auth_context.AuthContext
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Runtime auth context constructed by the aiohttp handler per request.
---

# AuthContext

Defined in [`parrot_formdesigner.services.auth_context`](../summaries/mod:parrot_formdesigner.services.auth_context.md).

```python
class AuthContext(BaseModel)
```

Runtime auth context constructed by the aiohttp handler per request.

Distinct from ``core.auth.AuthConfig`` which is the schema-side declaration.
``AuthContext`` carries resolved credentials and is passed explicitly to
``OptionsLoader.fetch()`` / ``RemoteResponseResolver.resolve()`` / renderers.

Cascade: the same AuthContext flows into nested GROUP / ARRAY field
rendering without re-resolution.

Attributes:
    scheme: Auth scheme identifier — "none", "bearer", "api_key", or "custom".
    token: Bearer token or API key value. None if not applicable.
    headers: Raw outbound HTTP headers (pre-built for "custom" scheme).
    claims: Parsed JWT claims if available (e.g., for scope-checking).

## Methods

- `def resolve_for(self, auth_ref: str | None) -> dict[str, str]` — Return outbound HTTP headers for the given auth_ref.
