---
type: Wiki Entity
title: CycleError
id: class:parrot.knowledge.ontology.exceptions.CycleError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when an is_a edge would create a cycle in the concept DAG.
relates_to:
- concept: class:parrot.knowledge.ontology.exceptions.OntologyError
  rel: extends
---

# CycleError

Defined in [`parrot.knowledge.ontology.exceptions`](../summaries/mod:parrot.knowledge.ontology.exceptions.md).

```python
class CycleError(OntologyError)
```

Raised when an is_a edge would create a cycle in the concept DAG.

Cycle detection runs on every propose_isa_edge and approve call.
The cycle path is stored for debugging.

Args:
    message: Human-readable error description.
    cycle_path: Ordered list of node IDs/names forming the cycle.
