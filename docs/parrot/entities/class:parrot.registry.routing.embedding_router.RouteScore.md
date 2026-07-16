---
type: Wiki Entity
title: RouteScore
id: class:parrot.registry.routing.embedding_router.RouteScore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of :meth:`EmbeddingIntentRouter.route`.
---

# RouteScore

Defined in [`parrot.registry.routing.embedding_router`](../summaries/mod:parrot.registry.routing.embedding_router.md).

```python
class RouteScore(NamedTuple)
```

Result of :meth:`EmbeddingIntentRouter.route`.

Attributes:
    mode: Best-matching :class:`OutputMode`, or ``None`` when the best score
        is below the router's ``threshold`` (abstain).
    score: Max-cosine similarity of the winning mode.
    runner_up: Second-best mode's score (for margin/ambiguity checks);
        ``-1.0`` when there is no runner-up.
    ambiguous: ``True`` when ``score >= threshold`` and
        ``(score - runner_up) < margin`` — i.e. the winner is not clearly
        ahead and a caller may wish to consult an LLM tie-breaker.
