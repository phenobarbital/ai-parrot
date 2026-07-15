---
type: Wiki Entity
title: GigSmartConfig
id: class:parrot_tools.interfaces.gigsmart.config.GigSmartConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for the GigSmart API client.
---

# GigSmartConfig

Defined in [`parrot_tools.interfaces.gigsmart.config`](../summaries/mod:parrot_tools.interfaces.gigsmart.config.md).

```python
class GigSmartConfig(BaseModel)
```

Configuration for the GigSmart API client.

All fields can be provided explicitly (useful for testing) or loaded
from environment variables via :meth:`from_env`.

Args:
    client_id: OAuth 2.1 client identifier.
    client_secret: OAuth 2.1 client secret.
    environment: Target environment — ``"production"`` or ``"sandbox"``.
    endpoint_url: GraphQL API endpoint URL.
    token_url: OAuth token endpoint URL.
    authorize_url: OAuth authorisation endpoint URL.
    request_timeout: Per-request timeout in seconds.
    max_concurrent_requests: Maximum number of parallel HTTP requests (>= 1).
    log_pii: When ``True``, PII (names, addresses) may appear in logs.
    refresh_token: Pre-configured OAuth refresh token, if available.

## Methods

- `def from_env(cls) -> 'GigSmartConfig'` — Build a ``GigSmartConfig`` from environment variables.
