---
type: Wiki Entity
title: StoreRouterConfig
id: class:parrot.registry.routing.models.StoreRouterConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Full configuration for ``StoreRouter``.
---

# StoreRouterConfig

Defined in [`parrot.registry.routing.models`](../summaries/mod:parrot.registry.routing.models.md).

```python
class StoreRouterConfig(BaseModel)
```

Full configuration for ``StoreRouter``.

Shape mirrors ``IntentRouterConfig`` from
``parrot.registry.capabilities.models``.

Args:
    margin_threshold: If ``top-1_confidence - top-2_confidence <
        margin_threshold``, engage the LLM fallback path.
    confidence_floor: Drop stores whose final score falls below this
        value from the ``StoreRoutingDecision.rankings``.
    llm_timeout_s: Maximum seconds to wait for the LLM ranking call.
    top_n: How many top-ranked stores to query in ``StoreRouter.execute``.
    fallback_policy: What to do when ``rankings`` is empty after
        applying the confidence floor.
    cache_size: Maximum number of ``StoreRoutingDecision`` entries to
        keep in the in-memory LRU.  ``0`` disables caching.
    enable_ontology_signal: Whether to query ``OntologyPreAnnotator``
        for query pre-annotation signals.
    custom_rules: Per-agent ``StoreRule`` list merged *on top of* the
        built-in default rules.  Follows the same precedence semantics as
        ``IntentRouterConfig.custom_keywords``.
