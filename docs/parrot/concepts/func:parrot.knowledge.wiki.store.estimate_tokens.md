---
type: Concept
title: estimate_tokens()
id: func:parrot.knowledge.wiki.store.estimate_tokens
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Cheap deterministic token estimate for budget accounting.
---

# estimate_tokens

```python
def estimate_tokens(text: str) -> int
```

Cheap deterministic token estimate for budget accounting.

Uses ``tiktoken`` (``cl100k_base``) when available, falling back to
the ``len(text) // 4`` heuristic.  The result is stored per page so
context packing can budget without re-tokenising at query time.

Args:
    text: Text to measure.

Returns:
    Estimated token count (>= 0).
