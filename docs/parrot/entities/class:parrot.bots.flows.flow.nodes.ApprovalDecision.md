---
type: Wiki Entity
title: ApprovalDecision
id: class:parrot.bots.flows.flow.nodes.ApprovalDecision
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Approval gate decision schema.
---

# ApprovalDecision

Defined in [`parrot.bots.flows.flow.nodes`](../summaries/mod:parrot.bots.flows.flow.nodes.md).

```python
class ApprovalDecision(BaseModel)
```

Approval gate decision schema.

Attributes:
    decision: The decision value (APPROVE, REJECT, or ESCALATE).
    confidence: Confidence level from 0.0 to 1.0.
    reasoning: Explanation for the decision.
    escalation_reason: Optional reason for escalation.
