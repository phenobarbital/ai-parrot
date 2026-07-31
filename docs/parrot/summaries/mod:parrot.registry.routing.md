---
type: Wiki Summary
title: parrot.registry.routing
id: mod:parrot.registry.routing
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: parrot.registry.routing — Store-level router for FEAT-111.
relates_to:
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
- concept: mod:parrot.registry.routing.store_router
  rel: references
- concept: mod:parrot.registry.routing.yaml_loader
  rel: references
---

# `parrot.registry.routing`

parrot.registry.routing — Store-level router for FEAT-111.

Public symbols::

    from parrot.registry.routing import (
        # Models (TASK-785)
        StoreFallbackPolicy,
        StoreRule,
        StoreRouterConfig,
        StoreScore,
        StoreRoutingDecision,
        # YAML loader (TASK-786)
        load_store_router_config,
        # LLM helper (TASK-787)
        extract_json_from_response,
        run_llm_ranking,
        # Rules engine (TASK-788)
        apply_rules,
        DEFAULT_STORE_RULES,
        # Ontology adapter (TASK-789)
        OntologyPreAnnotator,
        # Cache (TASK-790)
        DecisionCache,
        build_cache_key,
        # Core router (TASK-792)
        StoreRouter,
        NoSuitableStoreError,
    )
