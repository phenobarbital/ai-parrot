---
type: Wiki Entity
title: SecurityRequirement
id: class:parrot.a2a.models.SecurityRequirement
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'A security requirement: a map of scheme name -> required scopes.'
---

# SecurityRequirement

Defined in [`parrot.a2a.models`](../summaries/mod:parrot.a2a.models.md).

```python
class SecurityRequirement
```

A security requirement: a map of scheme name -> required scopes.

## Methods

- `def to_dict(self, version: str='1.0') -> Dict[str, Any]`
- `def from_dict(cls, data: Dict[str, Any]) -> 'SecurityRequirement'`
