---
type: Wiki Entity
title: SignalRelevanceConfig
id: class:parrot.knowledge.graphindex.signals.SignalRelevanceConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for the five-signal relevance scorer.
---

# SignalRelevanceConfig

Defined in [`parrot.knowledge.graphindex.signals`](../summaries/mod:parrot.knowledge.graphindex.signals.md).

```python
class SignalRelevanceConfig(BaseModel)
```

Configuration for the five-signal relevance scorer.

Weights sum to 1.0; the validator enforces it. The embedding weight
is independent of whether an embedder is actually supplied to the
scorer — when it isn't, the remaining four weights are
auto-renormalised at scoring time (the config itself is frozen).
