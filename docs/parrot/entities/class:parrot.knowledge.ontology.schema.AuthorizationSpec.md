---
type: Wiki Entity
title: AuthorizationSpec
id: class:parrot.knowledge.ontology.schema.AuthorizationSpec
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Declarative authorization specification for a traversal pattern.
---

# AuthorizationSpec

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class AuthorizationSpec(BaseModel)
```

Declarative authorization specification for a traversal pattern.

Rules are evaluated with OR semantics: the first matching rule allows access.
If no rule matches and ``default_deny=True``, access is denied.

Args:
    rules: List of authorization rules to evaluate in order.
    default_deny: Whether to deny when no rule matches (default True).
