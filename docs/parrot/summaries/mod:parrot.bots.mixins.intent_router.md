---
type: Wiki Summary
title: parrot.bots.mixins.intent_router
id: mod:parrot.bots.mixins.intent_router
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: IntentRouterMixin — pre-RAG query routing for AI-Parrot bots.
relates_to:
- concept: class:parrot.bots.mixins.intent_router.IntentRouterMixin
  rel: defines
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.registry.capabilities.models
  rel: references
- concept: mod:parrot.registry.capabilities.registry
  rel: references
- concept: mod:parrot.registry.routing.embedding_router
  rel: references
- concept: mod:parrot.registry.routing.llm_helper
  rel: references
---

# `parrot.bots.mixins.intent_router`

IntentRouterMixin — pre-RAG query routing for AI-Parrot bots.

Intercepts ``conversation()`` calls and routes the user query to the most
appropriate strategy (dataset query, vector search, tool call, graph traversal,
free LLM, etc.) before delegating to the base ``conversation()`` implementation.

Usage::

    class MyAgent(IntentRouterMixin, BasicAgent):
        pass

    agent = MyAgent(...)
    await agent.configure_router(config, registry)
    result = await agent.conversation("What were our Q1 sales?")

MRO note: ``IntentRouterMixin`` MUST appear before the concrete bot class in
the inheritance list so its ``conversation()`` method is called first.

Cross-feature dependency: The LLM routing path uses ``self.invoke()``
(FEAT-069). If invoke() is not available, the mixin falls back gracefully to
FREE_LLM.

## Classes

- **`IntentRouterMixin`** — Mixin that adds intent-based routing to any Bot or Agent.
