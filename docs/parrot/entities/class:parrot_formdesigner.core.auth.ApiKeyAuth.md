---
type: Wiki Entity
title: ApiKeyAuth
id: class:parrot_formdesigner.core.auth.ApiKeyAuth
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: API key authentication resolved from an environment variable.
---

# ApiKeyAuth

Defined in [`parrot_formdesigner.core.auth`](../summaries/mod:parrot_formdesigner.core.auth.md).

```python
class ApiKeyAuth(BaseModel)
```

API key authentication resolved from an environment variable.

The key is read from the environment at forwarding time — never
stored in the form schema.

Attributes:
    type: Discriminator literal, always ``"api_key"``.
    key_env: Name of the environment variable holding the API key.
    header_name: HTTP header to inject the key into. Defaults to ``"X-API-Key"``.

## Methods

- `def resolve(self) -> dict[str, str]` — Resolve the API key from env and return the configured header.
