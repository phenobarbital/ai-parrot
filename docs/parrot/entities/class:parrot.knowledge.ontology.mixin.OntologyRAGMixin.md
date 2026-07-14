---
type: Wiki Entity
title: OntologyRAGMixin
id: class:parrot.knowledge.ontology.mixin.OntologyRAGMixin
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mixin that adds Ontological Graph RAG capabilities to any agent.
---

# OntologyRAGMixin

Defined in [`parrot.knowledge.ontology.mixin`](../summaries/mod:parrot.knowledge.ontology.mixin.md).

```python
class OntologyRAGMixin
```

Mixin that adds Ontological Graph RAG capabilities to any agent.

Class-level constants
---------------------
``FILTERED_VECTOR_DOC_TYPES``: doc_type values used in Level-3 degradation
(filtered vector RAG).  Coupled to the ontology's authority document
taxonomy — change here when the knowledge.ontology.yaml adds new
authority ``doc_type`` values.

The mixin orchestrates the full ontology pipeline:

    1. Resolve tenant → merged ontology.
    2. Resolve intent (fast path or LLM path).
    3. **[NEW]** Extract + resolve named entities from the query.
    4. **[NEW]** Evaluate declarative authorization rules.
    5. Execute graph traversal if needed (existing).
    6. Apply post-action (vector_search, tool_call, or none).
    7. Cache the result.

Graceful degradation: if ArangoDB is unavailable, logs a warning
and returns ``ContextEnvelope(state="ok", context=EnrichedContext(source="vector_only"))``
without raising.

Args:
    tenant_manager: TenantOntologyManager instance.
    graph_store: OntologyGraphStore instance.
    vector_store: Existing PgVector store for post-action vector search.
    cache: OntologyCache instance (Redis-backed).
    llm_client: LLM client for intent resolver's LLM path.
    tool_manager: ToolManager instance for ToolCallDispatcher resolution.

## Methods

- `async def ontology_process(self, query: str, user_context: dict[str, Any], tenant_id: str, domain: str | None=None) -> ContextEnvelope` — Process a query through the ontology pipeline.
