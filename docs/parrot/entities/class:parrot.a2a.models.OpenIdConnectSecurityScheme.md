---
type: Wiki Entity
title: OpenIdConnectSecurityScheme
id: class:parrot.a2a.models.OpenIdConnectSecurityScheme
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: OpenID Connect security scheme.
relates_to:
- concept: class:parrot.a2a.models.SecurityScheme
  rel: extends
---

# OpenIdConnectSecurityScheme

Defined in [`parrot.a2a.models`](../summaries/mod:parrot.a2a.models.md).

```python
class OpenIdConnectSecurityScheme(SecurityScheme)
```

OpenID Connect security scheme.

## Methods

- `def to_dict(self, version: str='1.0') -> Dict[str, Any]`
- `def from_dict(cls, data: Dict[str, Any]) -> 'OpenIdConnectSecurityScheme'`
