---
type: Wiki Entity
title: HeuristicScorer
id: class:parrot.memory.episodic.scoring.HeuristicScorer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Heuristic importance scorer based on outcome and error type.
---

# HeuristicScorer

Defined in [`parrot.memory.episodic.scoring`](../summaries/mod:parrot.memory.episodic.scoring.md).

```python
class HeuristicScorer
```

Heuristic importance scorer based on outcome and error type.

Mirrors the inline logic in EpisodicMemoryStore.record_episode() and
normalizes the 1-10 scale to [0.0, 1.0].

Episodes with FAILURE or TIMEOUT outcome score higher (0.6-1.0),
PARTIAL scores mid-range (0.4-0.8), and SUCCESS scores lower (0.2-0.5).
Known error types (timeout, rate_limit, etc.) add a bonus.

## Methods

- `def score(self, episode: EpisodicMemory) -> float` — Compute normalized [0.0, 1.0] importance from outcome and error type.
