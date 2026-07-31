---
type: Wiki Entity
title: BinaryDecision
id: class:parrot.bots.flows.flow.nodes.BinaryDecision
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Binary YES/NO decision schema.
---

# BinaryDecision

Defined in [`parrot.bots.flows.flow.nodes`](../summaries/mod:parrot.bots.flows.flow.nodes.md).

```python
class BinaryDecision(BaseModel)
```

Binary YES/NO decision schema.

Attributes:
    decision: The decision value (YES or NO).
    confidence: Confidence level from 0.0 to 1.0.
    reasoning: Explanation for the decision.
