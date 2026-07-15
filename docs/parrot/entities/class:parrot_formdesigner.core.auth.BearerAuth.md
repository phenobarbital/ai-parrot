---
type: Wiki Entity
title: BearerAuth
id: class:parrot_formdesigner.core.auth.BearerAuth
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Bearer token authentication resolved from an environment variable.
---

# BearerAuth

Defined in [`parrot_formdesigner.core.auth`](../summaries/mod:parrot_formdesigner.core.auth.md).

```python
class BearerAuth(BaseModel)
```

Bearer token authentication resolved from an environment variable.

The token is read from the environment at forwarding time — never
stored in the form schema.

Attributes:
    type: Discriminator literal, always ``"bearer"``.
    token_env: Name of the environment variable holding the Bearer token.

## Methods

- `def resolve(self) -> dict[str, str]` — Resolve the Bearer token from env and return Authorization header.
