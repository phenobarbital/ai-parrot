---
type: Wiki Entity
title: DefaultPermissionResolver
id: class:parrot.auth.resolver.DefaultPermissionResolver
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Reference RBAC implementation with LRU-cached role expansion.
relates_to:
- concept: class:parrot.auth.resolver.AbstractPermissionResolver
  rel: extends
---

# DefaultPermissionResolver

Defined in [`parrot.auth.resolver`](../summaries/mod:parrot.auth.resolver.md).

```python
class DefaultPermissionResolver(AbstractPermissionResolver)
```

Reference RBAC implementation with LRU-cached role expansion.

This resolver implements role-based access control with hierarchical
role expansion. Roles can imply other roles (e.g., 'admin' implies
'write' which implies 'read').

The expansion is cached using LRU cache for performance. Cache is
per-resolver-instance; role hierarchy changes require a new resolver.

Attributes:
    _hierarchy: Dict mapping roles to their implied permissions/roles.
    _expand_cached: LRU-cached role expansion function.

Example:
    >>> hierarchy = {
    ...     'admin': {'manage', 'write', 'read'},
    ...     'manage': {'write', 'read'},
    ...     'write': {'read'},
    ...     'read': set(),
    ... }
    >>> resolver = DefaultPermissionResolver(role_hierarchy=hierarchy)
    >>> session = UserSession(user_id="u1", tenant_id="t1", roles=frozenset({'admin'}))
    >>> ctx = PermissionContext(session=session)
    >>> await resolver.can_execute(ctx, "create_issue", {'write'})
    True  # admin has write through hierarchy

## Methods

- `async def can_execute(self, context: PermissionContext, tool_name: str, required_permissions: set[str]) -> bool` — Check if user has any of the required permissions.
- `def clear_cache(self) -> None` — Clear the role expansion cache.
- `def cache_info(self) -> Any` — Return cache statistics for monitoring.
