---
type: Wiki Entity
title: RelationDef
id: class:parrot.knowledge.ontology.schema.RelationDef
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Definition of an edge collection (relation) in the ontology.
---

# RelationDef

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class RelationDef(BaseModel)
```

Definition of an edge collection (relation) in the ontology.

Uses ``from`` and ``to`` as YAML keys via aliases.

Args:
    from_entity: Source entity name.
    to_entity: Target entity name.
    edge_collection: ArangoDB edge collection name.
    properties: Edge properties.
    discovery: How to discover this relation in source data.
