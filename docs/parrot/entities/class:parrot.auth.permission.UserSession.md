---
type: Wiki Entity
title: UserSession
id: class:parrot.auth.permission.UserSession
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Minimal session carrying identity and role claims.
---

# UserSession

Defined in [`parrot.auth.permission`](../summaries/mod:parrot.auth.permission.md).

```python
class UserSession
```

Minimal session carrying identity and role claims.

Immutable and hashable — safe for use as cache keys in permission resolvers.

Attributes:
    user_id: Unique identifier for the user.
    tenant_id: Tenant/organization identifier for multi-tenant deployments.
    roles: Set of role claims (e.g., frozenset({'jira.manage', 'github.read'})).
        Uses frozenset for immutability and hashability.
    metadata: Optional additional session metadata (e.g., auth provider info).
        Note: metadata dict contents should be immutable for cache safety.

Example:
    >>> session = UserSession(
    ...     user_id="user-123",
    ...     tenant_id="acme-corp",
    ...     roles=frozenset({'jira.write', 'github.read'})
    ... )
    >>> 'jira.write' in session.roles
    True
    >>> hash(session)  # Hashable for cache keys
    -1234567890

## Methods

- `def has_role(self, role: str) -> bool` — Check if session has a specific role.
- `def has_any_role(self, roles: set[str] | frozenset[str]) -> bool` — Check if session has any of the specified roles.
