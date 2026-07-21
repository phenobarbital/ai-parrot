---
type: Wiki Entity
title: DiscoveryRule
id: class:parrot.knowledge.ontology.schema.DiscoveryRule
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Rule for discovering relationships between entities in source data.
---

# DiscoveryRule

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class DiscoveryRule(BaseModel)
```

Rule for discovering relationships between entities in source data.

Args:
    source_field: Field on the source entity (e.g. "Employee.project_code").
    target_field: Field on the target entity (e.g. "Project.project_id").
    match_type: Matching strategy to use.
    threshold: Confidence threshold for fuzzy/AI matching.
    description: Human-readable description of the rule.
