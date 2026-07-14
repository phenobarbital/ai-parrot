---
type: Wiki Entity
title: InteractiveDecisionNode
id: class:parrot.bots.flows.flow.nodes.InteractiveDecisionNode
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A Flow node that asks the user a multiple-choice question in the CLI.
relates_to:
- concept: class:parrot.bots.flows.core.node.Node
  rel: extends
---

# InteractiveDecisionNode

Defined in [`parrot.bots.flows.flow.nodes`](../summaries/mod:parrot.bots.flows.flow.nodes.md).

```python
class InteractiveDecisionNode(Node)
```

A Flow node that asks the user a multiple-choice question in the CLI.

Rewritten from legacy parrot.bots.flow.interactive_node.InteractiveDecisionNode
to subclass parrot.bots.flows.core.node.Node (frozen Pydantic).

Instead of using an LLM to decide routing, this node presents a list
of options directly to the user in the terminal and returns the selection.

Args:
    node_id: Unique identifier within the flow graph.
    question: The prompt text shown to the user.
    options: A list of string options to choose from.
    dependencies: Set of node_ids that must complete first.
    successors: Set of node_ids that depend on this one.
    fsm: Optional pre-constructed FSM (auto-created if None).

## Methods

- `def model_post_init(self, __context: Any) -> None` — Auto-create FSM and initialise logger.
- `def name(self) -> str` — Node identifier (name == node_id for interactive nodes).
- `async def ask(self, question: str='', **ctx: Any) -> DecisionResult` — Prompt the user in the terminal using questionary.
- `async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any) -> NodeResult` — Execute the interactive decision node within a FlowContext DAG.
- `async def configure(self) -> None` — No-op — nothing to configure.
