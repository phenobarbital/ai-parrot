---
type: Wiki Entity
title: StoreRoutingDecision
id: class:parrot.registry.routing.models.StoreRoutingDecision
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Complete output of ``StoreRouter.route()``.
---

# StoreRoutingDecision

Defined in [`parrot.registry.routing.models`](../summaries/mod:parrot.registry.routing.models.md).

```python
class StoreRoutingDecision(BaseModel)
```

Complete output of ``StoreRouter.route()``.

Args:
    rankings: Stores ranked by descending confidence.  May be empty when
        ``fallback_used`` is ``True``.
    fallback_used: ``True`` when no store cleared ``confidence_floor`` and
        the ``StoreFallbackPolicy`` was engaged.
    cache_hit: ``True`` when the decision was served from the LRU cache.
    ontology_annotations: Raw annotations produced by
        ``OntologyPreAnnotator.annotate()`` (if enabled).
    path: Decision path.  Conventional values:
        ``"cache"`` | ``"fast"`` | ``"llm"`` | ``"fallback"``.
    elapsed_ms: Wall-clock time from entering ``route()`` to returning the
        decision, in milliseconds.
