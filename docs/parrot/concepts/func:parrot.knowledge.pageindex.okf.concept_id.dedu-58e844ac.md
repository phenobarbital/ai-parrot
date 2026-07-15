---
type: Concept
title: dedup_concept_ids()
id: func:parrot.knowledge.pageindex.okf.concept_id.dedup_concept_ids
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolve slug collisions with stable numeric suffixes.
---

# dedup_concept_ids

```python
def dedup_concept_ids(nodes: list[dict]) -> None
```

Resolve slug collisions with stable numeric suffixes.

The first occurrence (in list order, which must be depth-first) keeps the
bare slug.  Subsequent duplicates receive ``-2``, ``-3``, etc.  The
assignment is stable across runs because the input list ordering is
deterministic (depth-first tree walk).

Modifies ``nodes`` in place.

Args:
    nodes: Flat list of node dicts, each with a ``concept_id`` key.
        Must be in depth-first order (same as produced by
        ``assign_concept_ids``).
