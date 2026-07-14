---
type: Concept
title: build_graphindex_ontology()
id: func:parrot.knowledge.graphindex.meta_ontology.build_graphindex_ontology
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return the universal GraphIndex meta-ontology as a ``MergedOntology``.
---

# build_graphindex_ontology

```python
def build_graphindex_ontology() -> MergedOntology
```

Return the universal GraphIndex meta-ontology as a ``MergedOntology``.

The returned object is additive — it defines new collections prefixed
with ``gi_`` that do not overlap with any existing tenant ontology.

Returns:
    A ``MergedOntology`` instance with 6 entities and 6 relations.
