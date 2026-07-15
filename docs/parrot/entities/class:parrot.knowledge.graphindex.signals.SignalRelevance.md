---
type: Wiki Entity
title: SignalRelevance
id: class:parrot.knowledge.graphindex.signals.SignalRelevance
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Decomposed pairwise relevance result.
---

# SignalRelevance

Defined in [`parrot.knowledge.graphindex.signals`](../summaries/mod:parrot.knowledge.graphindex.signals.md).

```python
class SignalRelevance(BaseModel)
```

Decomposed pairwise relevance result.

Combined score is the weighted sum of the (≤5) normalised signals.
The raw sub-signal payloads (edges, shared sources, AA neighbours)
are kept on the model so an LLM consumer can explain *why* two
nodes are related without re-running the scorer.
