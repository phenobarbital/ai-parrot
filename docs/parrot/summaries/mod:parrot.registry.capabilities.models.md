---
type: Wiki Summary
title: parrot.registry.capabilities.models
id: mod:parrot.registry.capabilities.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic v2 models for Intent Router and Capability Registry.
relates_to:
- concept: class:parrot.registry.capabilities.models.CapabilityEntry
  rel: defines
- concept: class:parrot.registry.capabilities.models.IntentRouterConfig
  rel: defines
- concept: class:parrot.registry.capabilities.models.ResourceType
  rel: defines
- concept: class:parrot.registry.capabilities.models.RouterCandidate
  rel: defines
- concept: class:parrot.registry.capabilities.models.RoutingDecision
  rel: defines
- concept: class:parrot.registry.capabilities.models.RoutingTrace
  rel: defines
- concept: class:parrot.registry.capabilities.models.RoutingType
  rel: defines
- concept: class:parrot.registry.capabilities.models.TraceEntry
  rel: defines
- concept: mod:parrot.registry.routing.models
  rel: references
---

# `parrot.registry.capabilities.models`

Pydantic v2 models for Intent Router and Capability Registry.

Defines all enums and data models for the FEAT-070 intent routing feature:
routing types, capability entries, routing decisions, routing traces, and
intent router configuration.

FEAT-111 addition: ``TraceEntry`` gains an optional ``store_rankings`` field
(list of ``StoreScore``) so the existing ``RoutingTrace`` machinery can carry
store-level detail when the ``StoreRouter`` is active.  The field defaults to
``None`` so all existing code that builds ``TraceEntry`` objects is unaffected.

## Classes

- **`ResourceType(str, Enum)`** — Type of resource registered in the capability index.
- **`RoutingType(str, Enum)`** — Strategy the intent router can select.
- **`CapabilityEntry(BaseModel)`** — A registered capability in the semantic index.
- **`RouterCandidate(BaseModel)`** — A scored match from capability search.
- **`RoutingDecision(BaseModel)`** — The router's selected strategy and candidates.
- **`TraceEntry(BaseModel)`** — One step in the routing trace.
- **`RoutingTrace(BaseModel)`** — Full trace of a routing session.
- **`IntentRouterConfig(BaseModel)`** — Configuration for the IntentRouter.
