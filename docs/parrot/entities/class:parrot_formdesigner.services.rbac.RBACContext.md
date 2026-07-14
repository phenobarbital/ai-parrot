---
type: Wiki Entity
title: RBACContext
id: class:parrot_formdesigner.services.rbac.RBACContext
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Runtime RBAC context projected for a user in a program.
---

# RBACContext

Defined in [`parrot_formdesigner.services.rbac`](../summaries/mod:parrot_formdesigner.services.rbac.md).

```python
class RBACContext(BaseModel)
```

Runtime RBAC context projected for a user in a program.

Used by handlers for shadow-mode gate-keeping. The authoritative
enforcement lives in nav-auth.

Attributes:
    user_id: Authenticated user identifier.
    program_id: Program context.
    permissions: List of ``PermissionRecord`` resolved for this user.
    groups: Group memberships resolved from ``auth.*`` (read-only).

## Methods

- `def has_permission(self, codename: str, scope: RBACScope | None=None) -> bool` — Return True if the user has the given permission at the given scope.
