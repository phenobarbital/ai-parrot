---
type: Wiki Entity
title: EntityDef
id: class:parrot.knowledge.ontology.schema.EntityDef
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Definition of a vertex collection (entity) in the ontology.
---

# EntityDef

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class EntityDef(BaseModel)
```

Definition of a vertex collection (entity) in the ontology.

When ``extend`` is True, this entity definition is merged with a parent
layer's definition of the same entity. Properties and vectorize fields
are concatenated; source is overridden.

Args:
    collection: ArangoDB collection name.
    source: Data source identifier (workday, jira, csv, etc.).
    key_field: Primary key field name.
    properties: List of property definitions (each dict maps name → PropertyDef).
    vectorize: Fields to embed in PgVector.
    extend: If True, merge with parent layer's definition.

## Methods

- `def get_property_names(self) -> set[str]` — Return the set of all property names defined on this entity.
