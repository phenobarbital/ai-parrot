---
type: Wiki Entity
title: PropertyDef
id: class:parrot.knowledge.ontology.schema.PropertyDef
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Single property definition for an entity.
---

# PropertyDef

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class PropertyDef(BaseModel)
```

Single property definition for an entity.

Args:
    type: Data type of the property.
    required: Whether the property is required.
    unique: Whether values must be unique.
    default: Default value when not provided.
    enum: Allowed values (optional constraint).
    description: Human-readable description.
