---
type: Wiki Entity
title: EntityResolver
id: class:parrot.knowledge.ontology.entity_resolver.EntityResolver
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extracts named-entity mentions from a query and resolves them to graph
---

# EntityResolver

Defined in [`parrot.knowledge.ontology.entity_resolver`](../summaries/mod:parrot.knowledge.ontology.entity_resolver.md).

```python
class EntityResolver
```

Extracts named-entity mentions from a query and resolves them to graph
``_id``s using per-rule strategies.

Designed to sit between ``OntologyIntentResolver.resolve()`` and
``OntologyGraphStore.execute_traversal()`` in the ``ontology_process``
pipeline.

Args:
    graph_store: ArangoDB wrapper for entity-lookup traversals.
    ontology: Merged ontology to discover entity collection names.
    llm_client: Optional LLM client; required for ``ai_assisted`` resolver.
    vector_store: Optional PgVectorStore for ``hybrid_concept_match`` vector
        search stage.  When ``None``, stage 2 is skipped.
    concept_instances: Optional list of concept objects/dicts for synonym
        matching in ``hybrid_concept_match`` stage 1.  Each item must
        expose ``concept_id``, ``label``, and ``synonyms`` (duck-typing).
        When ``None``, stage 1 is skipped and resolution goes directly to
        vector search.

## Methods

- `async def extract_and_resolve(self, pattern: TraversalPattern, query: str, user_context: dict[str, Any], tenant_id: str) -> dict[str, str]` — Extract entity mentions from ``query`` and resolve each to a graph ``_id``.
