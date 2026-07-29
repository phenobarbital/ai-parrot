---
type: Wiki Entity
title: RelatesTo
id: class:parrot.knowledge.okf.ontology.RelatesTo
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A typed edge in the knowledge graph.
---

# RelatesTo

Defined in [`parrot.knowledge.okf.ontology`](../summaries/mod:parrot.knowledge.okf.ontology.md).

```python
class RelatesTo(BaseModel)
```

A typed edge in the knowledge graph.

Attributes:
    concept: Target concept_id (stable identity).
    rel: Relation type. Defaults to ``references`` for untyped prose links.
