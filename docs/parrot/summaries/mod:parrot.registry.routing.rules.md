---
type: Wiki Summary
title: parrot.registry.routing.rules
id: mod:parrot.registry.routing.rules
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Fast-path rules engine for the store-level router (FEAT-111 Module 4).
relates_to:
- concept: func:parrot.registry.routing.rules.apply_rules
  rel: defines
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.registry.routing.models
  rel: references
---

# `parrot.registry.routing.rules`

Fast-path rules engine for the store-level router (FEAT-111 Module 4).

Provides a stateless :func:`apply_rules` function that scores candidate stores
based on heuristic keyword/regex rules.  Hardcoded default rules cover the most
common cases; per-agent ``StoreRule`` lists can be merged on top.

Usage::

    from parrot.registry.routing import apply_rules, DEFAULT_STORE_RULES
    from parrot.models import StoreType

    scores = apply_rules(
        "what is the relationship between suppliers and warehouses?",
        DEFAULT_STORE_RULES,
        [StoreType.PGVECTOR, StoreType.ARANGO],
        ontology_annotations={"action": "graph_query"},
    )
    # → [StoreScore(store=ARANGO, confidence=1.0, ...), ...]

## Functions

- `def apply_rules(query: str, rules: list[StoreRule], available_stores: list[StoreType], ontology_annotations: Optional[dict]) -> list[StoreScore]` — Score *available_stores* for *query* using the provided *rules*.
