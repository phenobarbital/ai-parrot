---
type: Wiki Entity
title: DecisionResult
id: class:parrot.bots.flows.flow.nodes.DecisionResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Structured result from a decision node.
---

# DecisionResult

Defined in [`parrot.bots.flows.flow.nodes`](../summaries/mod:parrot.bots.flows.flow.nodes.md).

```python
class DecisionResult(BaseModel)
```

Structured result from a decision node.

Attributes:
    decision_id: Unique identifier for this decision.
    mode: The decision mode used (CIO, BALLOT, CONSENSUS).
    final_decision: The actual decision value.
    confidence: Overall confidence level (0.0 to 1.0).
    votes: Dict of agent_name -> decision_value.
    vote_distribution: Dict of decision_value -> count.
    consensus_level: Consensus level (UNANIMOUS, MAJORITY, etc.).
    escalated: Whether the decision was escalated to HITL.
    escalation_reason: Reason for escalation if applicable.
    agent_responses: Dict of agent_name -> full response dict.
    execution_time: Total execution time in seconds.
    metadata: Additional metadata.
