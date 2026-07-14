---
type: Wiki Entity
title: NoAuth
id: class:parrot_formdesigner.core.auth.NoAuth
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: No authentication — default, backward-compatible.
---

# NoAuth

Defined in [`parrot_formdesigner.core.auth`](../summaries/mod:parrot_formdesigner.core.auth.md).

```python
class NoAuth(BaseModel)
```

No authentication — default, backward-compatible.

Attributes:
    type: Discriminator literal, always ``"none"``.

## Methods

- `def resolve(self) -> dict[str, str]` — Return empty auth headers (no authentication).
