---
type: Wiki Entity
title: InteractiveDecisionFlowNode
id: class:parrot.bots.flows.flow.flow.InteractiveDecisionFlowNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: DAG-executor wrapper for the CLI-blocking interactive decision node.
relates_to:
- concept: class:parrot.bots.flows.core.node.Node
  rel: extends
---

# InteractiveDecisionFlowNode

Defined in [`parrot.bots.flows.flow.flow`](../summaries/mod:parrot.bots.flows.flow.flow.md).

```python
class InteractiveDecisionFlowNode(Node)
```

DAG-executor wrapper for the CLI-blocking interactive decision node.

Registered in NODE_REGISTRY under ``"interactive_decision"``.  The
canonical implementation (with the interactive prompt logic) lives in
:class:`parrot.bots.flows.flow.nodes.InteractiveDecisionNode`.

This wrapper delegates ``execute()`` to a fresh canonical node per
invocation so per-run state is isolated.

Args:
    node_id: Unique identifier within the graph.
    question: The prompt text shown to the user.
    options: A list of string options to choose from.
    dependencies: Set of node_ids that must complete first.
    successors: Set of node_ids that depend on this one.
    fsm: Auto-created if None.

## Methods

- `def model_post_init(self, __context: Any) -> None` — Auto-create FSM and call parent hook.
- `def name(self) -> str` — Node identifier.
- `async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any) -> DecisionResult` — Present a CLI menu and return the user's selection as a DecisionResult.
