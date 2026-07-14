---
type: Wiki Summary
title: parrot.registry.routing.models
id: mod:parrot.registry.routing.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic v2 data models for the FEAT-111 store-level router.
relates_to:
- concept: class:parrot.registry.routing.models.StoreFallbackPolicy
  rel: defines
- concept: class:parrot.registry.routing.models.StoreRouterConfig
  rel: defines
- concept: class:parrot.registry.routing.models.StoreRoutingDecision
  rel: defines
- concept: class:parrot.registry.routing.models.StoreRule
  rel: defines
- concept: class:parrot.registry.routing.models.StoreScore
  rel: defines
- concept: mod:parrot.models
  rel: references
---

# `parrot.registry.routing.models`

Pydantic v2 data models for the FEAT-111 store-level router.

These models mirror the shape of ``IntentRouterConfig`` and friends in
``parrot.registry.capabilities.models`` but are scoped to store selection.

Public API (re-exported from ``parrot.registry.routing``)::

    from parrot.registry.routing import (
        StoreFallbackPolicy,
        StoreRule,
        StoreRouterConfig,
        StoreScore,
        StoreRoutingDecision,
    )

## Classes

- **`StoreFallbackPolicy(str, Enum)`** — What the router does when no store scores above ``confidence_floor``.
- **`StoreRule(BaseModel)`** — One heuristic rule that maps a query pattern to a preferred store.
- **`StoreRouterConfig(BaseModel)`** — Full configuration for ``StoreRouter``.
- **`StoreScore(BaseModel)`** — One ranked store entry within a ``StoreRoutingDecision``.
- **`StoreRoutingDecision(BaseModel)`** — Complete output of ``StoreRouter.route()``.
