---
type: Wiki Entity
title: OntologyMerger
id: class:parrot.knowledge.ontology.merger.OntologyMerger
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Merge multiple ontology YAML layers into a single MergedOntology.
---

# OntologyMerger

Defined in [`parrot.knowledge.ontology.merger`](../summaries/mod:parrot.knowledge.ontology.merger.md).

```python
class OntologyMerger
```

Merge multiple ontology YAML layers into a single MergedOntology.

Merge rules:

**Entities with extend=True:**
    - properties: concatenated (no name collisions allowed)
    - vectorize: unioned
    - source: overridden (last layer wins)
    - key_field, collection: immutable

**Entities without extend=True:**
    - If entity already exists → OntologyMergeError
    - If entity is new → added

**Relations:**
    - New relation → added (endpoints validated)
    - Same name → from/to immutable, discovery.rules concatenated

**Traversal patterns:**
    - New → added
    - Same name → trigger_intents concatenated (deduped),
      query_template overridden, post_action overridden

## Methods

- `def merge(self, yaml_paths: list[Path]) -> MergedOntology` — Merge multiple YAML layers sequentially into a MergedOntology.
- `def merge_definitions(self, definitions: list[OntologyDefinition]) -> MergedOntology` — Merge pre-loaded OntologyDefinition objects (no file I/O).
- `def merge_with_overlay(self, yaml_paths: list[Path], overlay_defs: list[OntologyDefinition]) -> MergedOntology` — Merge YAML layers + in-memory PG-sourced overlay definitions.
