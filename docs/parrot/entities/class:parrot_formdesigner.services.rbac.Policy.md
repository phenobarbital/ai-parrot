---
type: Wiki Entity
title: Policy
id: class:parrot_formdesigner.services.rbac.Policy
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Declarative ABAC/PBAC policy — mirrors the nav-auth YAML format.
---

# Policy

Defined in [`parrot_formdesigner.services.rbac`](../summaries/mod:parrot_formdesigner.services.rbac.md).

```python
class Policy(BaseModel)
```

Declarative ABAC/PBAC policy — mirrors the nav-auth YAML format.

Attributes:
    name: Unique policy identifier (UNIQUE constraint in DB).
    effect: "allow" or "deny".
    description: Human-readable description.
    resources: List of resource patterns (e.g. ``["form:*", "agent:chat"]``).
    actions: List of permitted/denied action patterns.
    subjects: Dict with ``groups`` and/or ``users`` keys.
    conditions: Optional conditions dict (e.g. environment, resource).
    priority: Numeric priority; lower = evaluated first. Default 50.
    enforcing: When False, policy is in shadow mode (log only). Default False.
    tenant: Tenant scope for this policy, or None for global.
