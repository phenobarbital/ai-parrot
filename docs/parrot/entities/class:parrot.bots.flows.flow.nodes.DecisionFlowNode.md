---
type: Wiki Entity
title: DecisionFlowNode
id: class:parrot.bots.flows.flow.nodes.DecisionFlowNode
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Decision orchestrator node for AgentsFlow workflows.
relates_to:
- concept: class:parrot.bots.flows.core.node.Node
  rel: extends
---

# DecisionFlowNode

Defined in [`parrot.bots.flows.flow.nodes`](../summaries/mod:parrot.bots.flows.flow.nodes.md).

```python
class DecisionFlowNode(Node)
```

Decision orchestrator node for AgentsFlow workflows.

Rewritten from legacy parrot.bots.flow.decision_node.DecisionFlowNode
to subclass parrot.bots.flows.core.node.Node (frozen Pydantic).

NOT an agent itself — a container that orchestrates multiple agents
to make decisions. Three operating modes:
- CIO: Single coordinator agent decides, can escalate to HITL
- BALLOT: Multiple agents vote, results aggregated with optional weighting
- CONSENSUS: Agents read each other's decisions, coordinator synthesizes

The frozen Pydantic model stores per-configuration state as fields.
Per-run mutable state uses FlowContext.shared_data[self.node_id].

Args:
    node_id: Unique identifier within the flow graph.
    agents: Dict of agent_name -> agent instances participating in decision.
    config: DecisionNodeConfig with mode and parameters.
    default_question_template: Template for decision prompt if not provided.
    dependencies: Set of node_ids that must complete first.
    successors: Set of node_ids that depend on this one.
    fsm: Optional pre-constructed FSM (auto-created if None).

## Methods

- `def model_post_init(self, __context: Any) -> None` — Auto-create FSM and initialise logger.
- `def name(self) -> str` — Node identifier (name == node_id for decision nodes).
- `async def ask(self, question: str='', **ctx: Any) -> DecisionResult` — Execute decision-making process with pre/post action hooks.
- `async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any) -> NodeResult` — Execute the decision node within a FlowContext DAG.
