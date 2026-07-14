---
type: Wiki Entity
title: RBACScope
id: class:parrot_formdesigner.services.rbac.RBACScope
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Vocabulary of RBAC scopes that compile to ABAC policies.
---

# RBACScope

Defined in [`parrot_formdesigner.services.rbac`](../summaries/mod:parrot_formdesigner.services.rbac.md).

```python
class RBACScope(str, Enum)
```

Vocabulary of RBAC scopes that compile to ABAC policies.

Values:
    OWN: Access restricted to resources owned by the user.
    TEAM: Access to resources owned by the user's team.
    CLIENT: Access to all resources within a client boundary.
    GLOBAL: Unrestricted access within a tenant.
