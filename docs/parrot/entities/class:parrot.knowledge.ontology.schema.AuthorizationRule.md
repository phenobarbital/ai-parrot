---
type: Wiki Entity
title: AuthorizationRule
id: class:parrot.knowledge.ontology.schema.AuthorizationRule
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Single declarative authorization rule for an intent pattern.
---

# AuthorizationRule

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class AuthorizationRule(BaseModel)
```

Single declarative authorization rule for an intent pattern.

Args:
    rule: Which rule to evaluate.
    role: Required when ``rule == "has_role"``; the role name to check.
    description: Human-readable description.
