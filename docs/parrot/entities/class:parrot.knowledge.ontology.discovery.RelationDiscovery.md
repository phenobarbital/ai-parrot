---
type: Wiki Entity
title: RelationDiscovery
id: class:parrot.knowledge.ontology.discovery.RelationDiscovery
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Discover and create relationships between entities in the graph.
---

# RelationDiscovery

Defined in [`parrot.knowledge.ontology.discovery`](../summaries/mod:parrot.knowledge.ontology.discovery.md).

```python
class RelationDiscovery
```

Discover and create relationships between entities in the graph.

Strategies:
    - exact: Direct equality join between source and target fields.
    - fuzzy: Normalized string matching with configurable threshold (rapidfuzz).
    - ai_assisted: Batch LLM resolution for ambiguous pairs.
    - composite: Multi-field weighted scoring.

Args:
    llm_client: Optional LLM client for AI-assisted strategy.
    review_dir: Directory for review queue JSON files. If None, review
        entries are returned but not written to disk.

## Methods

- `async def discover(self, ctx: TenantContext, relation_def: RelationDef, source_data: list[dict[str, Any]], target_data: list[dict[str, Any]]) -> DiscoveryResult` — Discover edges between source and target entities.
