---
type: Wiki Entity
title: CallerIdentity
id: class:parrot.a2a.security.CallerIdentity
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Represents the authenticated identity of a calling agent.
---

# CallerIdentity

Defined in [`parrot.a2a.security`](../summaries/mod:parrot.a2a.security.md).

```python
class CallerIdentity(BaseModel)
```

Represents the authenticated identity of a calling agent.

This is the result of successful authentication and contains
all information needed for authorization decisions.

## Methods

- `def model_post_init(self, __context: Any) -> None` — Set issued_at to now if not provided.
- `def has_permission(self, permission: str) -> bool` — Check if caller has a specific permission.
- `def can_invoke_skill(self, skill_id: str) -> bool` — Check if caller can invoke a specific skill.
- `def has_role(self, role: str) -> bool` — Check if caller has a specific role.
- `def has_scope(self, scope: str) -> bool` — Check if caller has a specific OAuth2 scope.
- `def is_expired(self) -> bool` — Check if identity has expired.
- `def to_dict(self) -> Dict[str, Any]` — Convert to dictionary for serialization (backward-compat wrapper).
- `def from_dict(cls, data: Dict[str, Any]) -> 'CallerIdentity'` — Create from dictionary (backward-compat wrapper for model_validate).
