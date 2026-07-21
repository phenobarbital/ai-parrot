---
type: Wiki Entity
title: MultiChoiceDecision
id: class:parrot.bots.flows.flow.nodes.MultiChoiceDecision
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Multi-option choice decision schema.
---

# MultiChoiceDecision

Defined in [`parrot.bots.flows.flow.nodes`](../summaries/mod:parrot.bots.flows.flow.nodes.md).

```python
class MultiChoiceDecision(BaseModel)
```

Multi-option choice decision schema.

Attributes:
    decision: The chosen option key.
    confidence: Confidence level from 0.0 to 1.0.
    reasoning: Explanation for the decision.
    alternatives_considered: List of other options considered.
