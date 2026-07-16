---
type: Wiki Entity
title: FrameworkOverrideError
id: class:parrot.knowledge.ontology.exceptions.FrameworkOverrideError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when an overlay attempts to mutate a framework entity, relation, or
  pattern.
relates_to:
- concept: class:parrot.knowledge.ontology.exceptions.OntologyError
  rel: extends
---

# FrameworkOverrideError

Defined in [`parrot.knowledge.ontology.exceptions`](../summaries/mod:parrot.knowledge.ontology.exceptions.md).

```python
class FrameworkOverrideError(OntologyError)
```

Raised when an overlay attempts to mutate a framework entity, relation, or pattern.

Framework items (those in base.ontology.yaml) are immutable at runtime.
No UI path or PG overlay may redefine them.

Args:
    message: Human-readable error description.
    entity_name: Name of the framework entity/relation/pattern that was targeted.
