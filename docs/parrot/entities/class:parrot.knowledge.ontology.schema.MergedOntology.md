---
type: Wiki Entity
title: MergedOntology
id: class:parrot.knowledge.ontology.schema.MergedOntology
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Fully resolved ontology after merging all YAML layers.
---

# MergedOntology

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class MergedOntology(BaseModel)
```

Fully resolved ontology after merging all YAML layers.

This is the runtime representation used by the intent resolver,
graph store, and mixin.

Args:
    name: Name of the last merged layer.
    version: Schema version.
    entities: All entity definitions.
    relations: All relation definitions.
    traversal_patterns: All traversal patterns.
    layers: List of YAML file paths that were merged.
    merge_timestamp: When the merge was performed.

## Methods

- `def get_entity_collections(self) -> list[str]` — Return all vertex collection names.
- `def get_edge_collections(self) -> list[str]` — Return all edge collection names.
- `def get_vectorizable_fields(self, entity_name: str) -> list[str]` — Return fields that should be embedded in PgVector for an entity.
- `def build_schema_prompt(self) -> str` — Generate a natural language description of the ontology for the LLM.
