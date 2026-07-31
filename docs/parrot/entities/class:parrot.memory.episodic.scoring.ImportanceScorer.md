---
type: Wiki Entity
title: ImportanceScorer
id: class:parrot.memory.episodic.scoring.ImportanceScorer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Protocol for pluggable importance scoring strategies.
---

# ImportanceScorer

Defined in [`parrot.memory.episodic.scoring`](../summaries/mod:parrot.memory.episodic.scoring.md).

```python
class ImportanceScorer(Protocol)
```

Protocol for pluggable importance scoring strategies.

Implementations return a float in [0.0, 1.0] representing the
importance of an episode (0 = trivial, 1 = critical).

## Methods

- `def score(self, episode: EpisodicMemory) -> float` — Return importance score for the given episode.
