---
type: Wiki Entity
title: OntologyDefinition
id: class:parrot.knowledge.ontology.schema.OntologyDefinition
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Root model for a single ontology YAML layer.
---

# OntologyDefinition

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class OntologyDefinition(BaseModel)
```

Root model for a single ontology YAML layer.

Each YAML file is parsed into this model. Multiple OntologyDefinition
instances are then merged by OntologyMerger to produce a MergedOntology.

Args:
    name: Ontology layer name.
    version: Schema version.
    extends: Parent ontology name (for documentation).
    description: Human-readable description.
    entities: Entity definitions keyed by name.
    relations: Relation definitions keyed by name.
    traversal_patterns: Traversal pattern definitions keyed by name.
