---
type: Wiki Summary
title: parrot.registry.routing.store_router
id: mod:parrot.registry.routing.store_router
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: StoreRouter core orchestrator (FEAT-111 Module 7).
relates_to:
- concept: class:parrot.registry.routing.store_router.NoSuitableStoreError
  rel: defines
- concept: class:parrot.registry.routing.store_router.StoreRouter
  rel: defines
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.registry.routing.cache
  rel: references
- concept: mod:parrot.registry.routing.llm_helper
  rel: references
- concept: mod:parrot.registry.routing.models
  rel: references
- concept: mod:parrot.registry.routing.ontology_signal
  rel: references
- concept: mod:parrot.registry.routing.rules
  rel: references
- concept: mod:parrot.stores.abstract
  rel: references
- concept: mod:parrot_tools.multistoresearch
  rel: references
---

# `parrot.registry.routing.store_router`

StoreRouter core orchestrator (FEAT-111 Module 7).

Integrates all sub-modules (cache, rules, ontology, LLM helper) into the
end-to-end store-routing decision + execution pipeline.

Usage::

    from parrot.registry.routing import StoreRouter, StoreRouterConfig

    router = StoreRouter(config)
    decision = await router.route("what is an endcap?", [StoreType.PGVECTOR])
    results  = await router.execute(decision, query, stores_dict)

## Classes

- **`NoSuitableStoreError(RuntimeError)`** — Raised by ``StoreRouter.execute`` when ``fallback_policy=RAISE``
- **`StoreRouter`** — Store-level router activated via ``AbstractBot.configure_store_router()``.
