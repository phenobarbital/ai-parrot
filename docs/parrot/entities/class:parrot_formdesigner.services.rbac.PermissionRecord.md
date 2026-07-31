---
type: Wiki Entity
title: PermissionRecord
id: class:parrot_formdesigner.services.rbac.PermissionRecord
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A compiled permission entry (result of assign_role).
---

# PermissionRecord

Defined in [`parrot_formdesigner.services.rbac`](../summaries/mod:parrot_formdesigner.services.rbac.md).

```python
class PermissionRecord(BaseModel)
```

A compiled permission entry (result of assign_role).

Attributes:
    user_id: The user this record belongs to.
    codename: Permission code (e.g. "edit_form").
    scope: The ``RBACScope`` the permission was issued with.
    program_id: Program context for the permission.
    policy_name: Name of the generated ``Policy`` in DB.
    tenant: Tenant this record is scoped to.
