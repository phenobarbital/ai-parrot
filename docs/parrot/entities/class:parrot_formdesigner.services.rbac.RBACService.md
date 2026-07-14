---
type: Wiki Entity
title: RBACService
id: class:parrot_formdesigner.services.rbac.RBACService
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manage ABAC/PBAC policies in ``fieldsync.auth_policies`` + project context.
---

# RBACService

Defined in [`parrot_formdesigner.services.rbac`](../summaries/mod:parrot_formdesigner.services.rbac.md).

```python
class RBACService
```

Manage ABAC/PBAC policies in ``fieldsync.auth_policies`` + project context.

All writes target ``fieldsync.*`` exclusively — NEVER ``auth.*``.
Auth tables are only read (read-only pool) for group resolution.

Args:
    pool: asyncpg pool (or fake pool for tests).

Example::

    svc = RBACService(pool)
    record = await svc.assign_role(
        "user-1", program_id=7, codename="edit_form",
        scope=RBACScope.OWN, tenant="acme"
    )
    ctx = await svc.resolve("user-1", program_id=7, tenant="acme")
    assert ctx.has_permission("edit_form", scope=RBACScope.OWN)

## Methods

- `async def create_policy(self, policy: Policy) -> Policy` — Upsert a policy in ``fieldsync.auth_policies``.
- `async def get_policy(self, name: str) -> Policy | None` — Retrieve a policy by name.
- `async def list_policies(self, *, tenant: str) -> list[Policy]` — List all policies for a tenant, ordered by priority.
- `async def delete_policy(self, name: str) -> bool` — Delete a policy by name.
- `async def assign_role(self, user_id: str, *, program_id: int, codename: str, scope: RBACScope, tenant: str) -> PermissionRecord` — Compile (user_id, codename, scope) to a Policy and persist it.
- `async def resolve(self, user_id: str, *, program_id: int, tenant: str) -> RBACContext` — Build ``RBACContext`` for a user by reading ``fieldsync.auth_policies``.
- `async def revoke_all(self, user_id: str, *, tenant: str) -> int` — Delete all policies compiled for ``user_id`` in ``tenant``.
