---
type: Wiki Entity
title: HTTPAuthSecurityScheme
id: class:parrot.a2a.models.HTTPAuthSecurityScheme
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: HTTP authentication security scheme (Bearer/Basic).
relates_to:
- concept: class:parrot.a2a.models.SecurityScheme
  rel: extends
---

# HTTPAuthSecurityScheme

Defined in [`parrot.a2a.models`](../summaries/mod:parrot.a2a.models.md).

```python
class HTTPAuthSecurityScheme(SecurityScheme)
```

HTTP authentication security scheme (Bearer/Basic).

## Methods

- `def to_dict(self, version: str='1.0') -> Dict[str, Any]`
- `def from_dict(cls, data: Dict[str, Any]) -> 'HTTPAuthSecurityScheme'`
