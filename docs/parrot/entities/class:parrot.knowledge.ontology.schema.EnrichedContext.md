---
type: Wiki Entity
title: EnrichedContext
id: class:parrot.knowledge.ontology.schema.EnrichedContext
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Enriched context returned by the ontology pipeline.
---

# EnrichedContext

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class EnrichedContext(BaseModel)
```

Enriched context returned by the ontology pipeline.

Contains structural (graph) and semantic (vector) information that
the agent uses to augment its LLM prompt.

Args:
    source: How the context was produced.
    graph_context: Results from graph traversal.
    vector_context: Results from vector search.
    tool_hint: Hint for tool execution from graph context.
    intent: The resolved intent that produced this context.
    metadata: Additional metadata.

## Methods

- `def to_cache(self) -> str` — Serialize to JSON string for Redis caching.
- `def from_cache(cls, cached: str) -> EnrichedContext` — Deserialize from cached JSON string.
