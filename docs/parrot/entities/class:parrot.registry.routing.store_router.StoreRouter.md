---
type: Wiki Entity
title: StoreRouter
id: class:parrot.registry.routing.store_router.StoreRouter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Store-level router activated via ``AbstractBot.configure_store_router()``.
---

# StoreRouter

Defined in [`parrot.registry.routing.store_router`](../summaries/mod:parrot.registry.routing.store_router.md).

```python
class StoreRouter
```

Store-level router activated via ``AbstractBot.configure_store_router()``.

Orchestration order within :meth:`route`:

1. LRU cache lookup.
2. Ontology pre-annotation (when ``enable_ontology_signal=True``).
3. Fast-path rules evaluation.
4. Margin check → LLM path (when margin is too narrow and ``invoke_fn``
   is provided).
5. Confidence floor filtering.
6. Decision assembly + cache write.

:meth:`execute` drives retrieval according to the decision's
``rankings`` and ``StoreFallbackPolicy``.

Args:
    config: Full router configuration.
    ontology_resolver: Optional resolver passed through to
        :class:`~parrot.registry.routing.OntologyPreAnnotator`.

## Methods

- `async def route(self, query: str, available_stores: list[StoreType], invoke_fn: Optional[Callable]=None) -> StoreRoutingDecision` — Produce a :class:`StoreRoutingDecision` for *query*.
- `async def execute(self, decision: StoreRoutingDecision, query: str, stores: dict[StoreType, 'AbstractStore'], multistore_tool: Optional['MultiStoreSearchTool']=None, **search_kwargs: Any) -> list` — Execute retrieval according to *decision*.
