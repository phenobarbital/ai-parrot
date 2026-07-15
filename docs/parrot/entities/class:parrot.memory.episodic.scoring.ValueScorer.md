---
type: Wiki Entity
title: ValueScorer
id: class:parrot.memory.episodic.scoring.ValueScorer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Heuristic interaction value scorer ported from AgentCoreMemory.
---

# ValueScorer

Defined in [`parrot.memory.episodic.scoring`](../summaries/mod:parrot.memory.episodic.scoring.md).

```python
class ValueScorer(BaseModel)
```

Heuristic interaction value scorer ported from AgentCoreMemory.

Assesses the value of an interaction using weighted signals:
- Outcome (SUCCESS adds value, FAILURE subtracts)
- Tool usage (non-conversational interactions add value)
- Query length (longer queries are typically more substantive)
- Response length (longer outcome_details indicate richer interactions)
- Implicit feedback from outcome details

All weights are configurable. Score is clamped to [0.0, 1.0].
Scores below ``threshold`` are considered low-value.

Args:
    outcome_weight: Weight for positive outcome signal. Default 0.3.
    tool_usage_weight: Weight for tool usage signal. Default 0.2.
    query_length_weight: Weight for substantive situation length. Default 0.1.
    response_length_weight: Weight for outcome_details length. Default 0.2.
    feedback_weight: Weight for explicit positive/negative signals. Default 0.3.
    threshold: Minimum score to be considered valuable. Default 0.4.

## Methods

- `def score(self, episode: EpisodicMemory) -> float` — Compute interaction value score for the given episode.
- `def is_valuable(self, episode: EpisodicMemory) -> bool` — Return True if the episode's value score meets the threshold.
