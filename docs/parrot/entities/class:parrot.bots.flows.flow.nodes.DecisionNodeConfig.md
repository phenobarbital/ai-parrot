---
type: Wiki Entity
title: DecisionNodeConfig
id: class:parrot.bots.flows.flow.nodes.DecisionNodeConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for DecisionFlowNode.
---

# DecisionNodeConfig

Defined in [`parrot.bots.flows.flow.nodes`](../summaries/mod:parrot.bots.flows.flow.nodes.md).

```python
class DecisionNodeConfig(BaseModel)
```

Configuration for DecisionFlowNode.

Attributes:
    mode: Operating mode (CIO, BALLOT, CONSENSUS).
    decision_type: Type of decision (BINARY, APPROVAL, MULTI_CHOICE, CUSTOM).
    decision_schema: Pydantic model for structured output.
    vote_weight_strategy: How to weight votes (for BALLOT/CONSENSUS).
    custom_weights: Custom weight values per agent.
    minimum_votes: Minimum number of votes required (quorum).
    coordinator_agent_name: Name of coordinator agent (for CONSENSUS).
    cross_pollination_rounds: Number of revision rounds (for CONSENSUS).
    escalation_policy: Escalation configuration.
    options: Available options (for MULTI_CHOICE).
