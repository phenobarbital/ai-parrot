---
type: Wiki Entity
title: AbstractOAuth2TokenSet
id: class:parrot.auth.oauth2_base.AbstractOAuth2TokenSet
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Provider-agnostic OAuth 2.0 token set.
---

# AbstractOAuth2TokenSet

Defined in [`parrot.auth.oauth2_base`](../summaries/mod:parrot.auth.oauth2_base.md).

```python
class AbstractOAuth2TokenSet(BaseModel)
```

Provider-agnostic OAuth 2.0 token set.

Subclasses extend with provider-specific identity fields
(e.g. ``tenant_id``, ``cloud_id``).

## Methods

- `def is_expired(self) -> bool` — Return ``True`` if the access token is at/past expiry (with leeway).
