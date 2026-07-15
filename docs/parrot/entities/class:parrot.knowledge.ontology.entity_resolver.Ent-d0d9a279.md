---
type: Wiki Entity
title: EntityAmbiguityError
id: class:parrot.knowledge.ontology.entity_resolver.EntityAmbiguityError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when multiple candidates match and the strategy is ``ask_user``
---

# EntityAmbiguityError

Defined in [`parrot.knowledge.ontology.entity_resolver`](../summaries/mod:parrot.knowledge.ontology.entity_resolver.md).

```python
class EntityAmbiguityError(Exception)
```

Raised when multiple candidates match and the strategy is ``ask_user``
or ``fail``.

Attributes:
    rule_name: Name of the entity extraction rule that triggered this error.
    mention: The extracted mention string.
    candidates: List of candidate dicts from the graph (each has ``_id``).
