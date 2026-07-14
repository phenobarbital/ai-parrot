---
type: Concept
title: rank_by_cosine()
id: func:parrot.knowledge.wiki.store.rank_by_cosine
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Rank candidate stubs by cosine similarity to a query vector.
---

# rank_by_cosine

```python
def rank_by_cosine(embedding: list[float], candidates: list[tuple[dict[str, Any], list[float]]], limit: int=10) -> list[dict[str, Any]]
```

Rank candidate stubs by cosine similarity to a query vector.

Shared by every backend — brute-force in-process scan, appropriate
at wiki scale (10³–10⁴ pages).  Candidates whose vector dimension
does not match the query are skipped.

Args:
    embedding: Query vector.
    candidates: ``(stub_dict, vector)`` pairs.
    limit: Maximum results.

Returns:
    Stub dicts with a ``score`` key in [-1, 1], best first.
