---
type: Wiki Entity
title: APIKeySecurityScheme
id: class:parrot.a2a.models.APIKeySecurityScheme
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: API key security scheme.
relates_to:
- concept: class:parrot.a2a.models.SecurityScheme
  rel: extends
---

# APIKeySecurityScheme

Defined in [`parrot.a2a.models`](../summaries/mod:parrot.a2a.models.md).

```python
class APIKeySecurityScheme(SecurityScheme)
```

API key security scheme.

## Methods

- `def to_dict(self, version: str='1.0') -> Dict[str, Any]`
- `def from_dict(cls, data: Dict[str, Any]) -> 'APIKeySecurityScheme'`
