---
type: Wiki Entity
title: UniversalEdge
id: class:parrot.knowledge.graphindex.schema.UniversalEdge
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A directed edge in the GraphIndex knowledge graph.
---

# UniversalEdge

Defined in [`parrot.knowledge.graphindex.schema`](../summaries/mod:parrot.knowledge.graphindex.schema.md).

```python
class UniversalEdge(BaseModel)
```

A directed edge in the GraphIndex knowledge graph.

The ``confidence`` field MUST be set (non-None) if and only if
``provenance == Provenance.INFERRED``.  A ``field_validator`` enforces
this invariant.

Args:
    source_id: ``node_id`` of the tail node.
    target_id: ``node_id`` of the head node.
    kind: Semantic category of this edge.
    provenance: How this edge was created.
    confidence: Cosine similarity score in [0, 1].  Required for
        ``INFERRED`` edges; must be ``None`` for others.
