---
type: Wiki Entity
title: DecisionNode
id: class:parrot.bots.flows.flow.flow.DecisionNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wraps the legacy DecisionFlowNode as a frozen Pydantic Node.
relates_to:
- concept: class:parrot.bots.flows.core.node.Node
  rel: extends
---

# DecisionNode

Defined in [`parrot.bots.flows.flow.flow`](../summaries/mod:parrot.bots.flows.flow.flow.md).

```python
class DecisionNode(Node)
```

Wraps the legacy DecisionFlowNode as a frozen Pydantic Node.

Holds a ``DecisionNodeConfig`` and a dict of participating agents;
constructs a fresh ``DecisionFlowNode`` on each ``execute()`` call so
per-run state is isolated (B-lite contract).

Args:
    node_id: Unique identifier within the graph.
    decision_config: Configuration for the decision node (mode, etc.).
    agents: Mapping of agent_name → agent instance participating in the
        decision. These are forwarded to the legacy DecisionFlowNode.
    dependencies: Set of node_ids that must complete first.
    successors: Set of node_ids that depend on this one.
    fsm: Auto-created if None.

## Methods

- `def model_post_init(self, __context: Any) -> None` — Auto-create FSM and call parent hook.
- `def name(self) -> str` — Node identifier.
- `async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any) -> DecisionResult` — Execute the decision node.
