---
type: Wiki Entity
title: EntityNotFoundError
id: class:parrot.knowledge.ontology.entity_resolver.EntityNotFoundError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when no candidates match a required entity extraction rule.
---

# EntityNotFoundError

Defined in [`parrot.knowledge.ontology.entity_resolver`](../summaries/mod:parrot.knowledge.ontology.entity_resolver.md).

```python
class EntityNotFoundError(Exception)
```

Raised when no candidates match a required entity extraction rule.

Attributes:
    rule_name: Name of the entity extraction rule that triggered this error.
    mention: The extracted mention string, or ``None`` if extraction failed.
