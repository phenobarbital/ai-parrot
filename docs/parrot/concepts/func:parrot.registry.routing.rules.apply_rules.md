---
type: Concept
title: apply_rules()
id: func:parrot.registry.routing.rules.apply_rules
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Score *available_stores* for *query* using the provided *rules*.
---

# apply_rules

```python
def apply_rules(query: str, rules: list[StoreRule], available_stores: list[StoreType], ontology_annotations: Optional[dict]) -> list[StoreScore]
```

Score *available_stores* for *query* using the provided *rules*.

Algorithm:
1. Lowercase the query once.
2. For each rule, check whether the query matches (substring or regex).
   If the rule's ``store`` is not in *available_stores* the rule is
   silently skipped.
3. For each store, keep only the **maximum** weight across all matching
   rules (do NOT sum — keeps confidences bounded in [0, 1]).
4. Apply ontology boosts (if *ontology_annotations* signals a preference).
5. Sort descending by confidence.

Args:
    query: Raw user query string.
    rules: ``StoreRule`` list to evaluate.  Typically the built-in
        :data:`DEFAULT_STORE_RULES` plus any per-agent custom rules.
    available_stores: Stores actually configured on the bot.  Rules
        targeting other stores are filtered out.
    ontology_annotations: Output of ``OntologyPreAnnotator.annotate()``.
        Pass ``None`` or ``{}`` when the ontology is not configured.

Returns:
    Ranked ``list[StoreScore]`` — descending by confidence.
    Empty list when no rules matched and no ontology signal applied.
