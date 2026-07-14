---
type: Wiki Entity
title: OAuth2SecurityScheme
id: class:parrot.a2a.models.OAuth2SecurityScheme
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: OAuth 2.0 security scheme.
relates_to:
- concept: class:parrot.a2a.models.SecurityScheme
  rel: extends
---

# OAuth2SecurityScheme

Defined in [`parrot.a2a.models`](../summaries/mod:parrot.a2a.models.md).

```python
class OAuth2SecurityScheme(SecurityScheme)
```

OAuth 2.0 security scheme.

## Methods

- `def to_dict(self, version: str='1.0') -> Dict[str, Any]`
- `def from_dict(cls, data: Dict[str, Any]) -> 'OAuth2SecurityScheme'`
