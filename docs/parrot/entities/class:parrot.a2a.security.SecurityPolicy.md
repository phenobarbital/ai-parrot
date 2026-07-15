---
type: Wiki Entity
title: SecurityPolicy
id: class:parrot.a2a.security.SecurityPolicy
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Security policy for an agent, endpoint, or skill.
---

# SecurityPolicy

Defined in [`parrot.a2a.security`](../summaries/mod:parrot.a2a.security.md).

```python
class SecurityPolicy(BaseModel)
```

Security policy for an agent, endpoint, or skill.

Defines authentication requirements and access control rules.

## Methods

- `def allows_scheme(self, scheme: AuthScheme) -> bool` — Check if authentication scheme is allowed.
- `def is_agent_allowed(self, agent_name: str) -> bool` — Check if a specific agent is allowed.
- `def check_permissions(self, identity: CallerIdentity) -> bool` — Check if identity has all required permissions.
- `def check_roles(self, identity: CallerIdentity) -> bool` — Check if identity has all required roles.
- `def check_scopes(self, identity: CallerIdentity) -> bool` — Check if identity has all required scopes.
