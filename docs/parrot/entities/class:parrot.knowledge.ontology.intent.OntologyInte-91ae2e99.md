---
type: Wiki Entity
title: OntologyIntentResolver
id: class:parrot.knowledge.ontology.intent.OntologyIntentResolver
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolve user queries into graph traversal intents.
---

# OntologyIntentResolver

Defined in [`parrot.knowledge.ontology.intent`](../summaries/mod:parrot.knowledge.ontology.intent.md).

```python
class OntologyIntentResolver
```

Resolve user queries into graph traversal intents.

Two resolution paths:

**Fast path** (deterministic, ~0ms):
    Scans query for keywords matching ``trigger_intents`` in traversal
    patterns. If match found, immediately returns the predefined pattern.

**LLM path** (~200-800ms):
    Sends query + ontology schema to LLM for classification using
    structured output. LLM either selects a known pattern or generates
    dynamic AQL.

The fast path is tried first. If no match, the LLM path is used.
If neither matches, returns ``vector_only``.

.. deprecated::
    Prefer :class:`parrot.bots.mixins.intent_router.IntentRouterMixin`
    as the primary routing mechanism. ``OntologyIntentResolver`` is now a
    sub-strategy within the intent router's ``GRAPH_PAGEINDEX`` path.
    It remains functional and will not be removed in the foreseeable future.

Args:
    ontology: The merged ontology for this tenant.
    llm_client: LLM client for the LLM path (optional — fast path works without it).

## Methods

- `async def resolve(self, query: str, user_context: dict[str, Any]) -> ResolvedIntent` — Resolve a user query into an intent.
