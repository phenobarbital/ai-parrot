---
type: Wiki Entity
title: EntityExtractionRule
id: class:parrot.knowledge.ontology.schema.EntityExtractionRule
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Rule describing how to extract and resolve a named entity from a query.
---

# EntityExtractionRule

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class EntityExtractionRule(BaseModel)
```

Rule describing how to extract and resolve a named entity from a query.

Args:
    type: Ontology entity type (e.g., ``"Employee"``).
    resolver: Resolution strategy to use.
    scope: Scope of the search: ``same_tenant``, ``same_department``, or
        ``anywhere``.
    ambiguity_strategy: What to do when multiple candidates match.
    required: If True, failure to resolve raises ``EntityNotFoundError``.
    description: Human-readable description of this rule.
