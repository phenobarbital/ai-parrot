---
type: Wiki Entity
title: AuthCredential
id: class:parrot.mcp.client.AuthCredential
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Type-safe credential container with validation.
---

# AuthCredential

Defined in [`parrot.mcp.client`](../summaries/mod:parrot.mcp.client.md).

```python
class AuthCredential(BaseModel)
```

Type-safe credential container with validation.

Validates that required fields are present based on the chosen scheme.

Example:
    >>> # Bearer token
    >>> cred = AuthCredential(scheme=AuthScheme.BEARER, token="my-token")

    >>> # API Key with custom header
    >>> cred = AuthCredential(
    ...     scheme=AuthScheme.API_KEY,
    ...     api_key="secret",
    ...     api_key_header="X-Custom-Key"
    ... )

    >>> # Get headers
    >>> headers = cred.get_auth_headers()

## Methods

- `def validate_scheme_requirements(self)` — Validate that required fields are set for chosen scheme.
- `def get_auth_headers(self) -> Dict[str, str]` — Generate appropriate auth headers based on scheme.
