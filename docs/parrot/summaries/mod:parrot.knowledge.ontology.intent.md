---
type: Wiki Summary
title: parrot.knowledge.ontology.intent
id: mod:parrot.knowledge.ontology.intent
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Dual-path intent resolution for ontology graph RAG.
relates_to:
- concept: class:parrot.knowledge.ontology.intent.IntentDecision
  rel: defines
- concept: class:parrot.knowledge.ontology.intent.OntologyIntentResolver
  rel: defines
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
- concept: mod:parrot.knowledge.ontology.validators
  rel: references
---

# `parrot.knowledge.ontology.intent`

Dual-path intent resolution for ontology graph RAG.

Resolves user queries into graph traversal intents using two paths:
    - Fast path (~0ms): keyword scan against trigger_intents.
    - LLM path (~200-800ms): structured output for ambiguous queries.

.. deprecated::
    ``OntologyIntentResolver`` is soft-deprecated in favour of
    :class:`parrot.bots.mixins.intent_router.IntentRouterMixin`, which provides
    unified routing across datasets, tools, vector stores, and graph sources.
    ``OntologyIntentResolver`` remains available and functional but is now a
    single-source sub-strategy within the broader intent routing framework.
    It will not be removed in the foreseeable future.

## Classes

- **`IntentDecision(BaseModel)`** — Structured output from LLM intent classification.
- **`OntologyIntentResolver`** — Resolve user queries into graph traversal intents.
