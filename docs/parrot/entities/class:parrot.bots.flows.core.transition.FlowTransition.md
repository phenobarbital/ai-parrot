---
type: Wiki Entity
title: FlowTransition
id: class:parrot.bots.flows.core.transition.FlowTransition
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Conditional edge between two nodes in a flow/crew DAG.
---

# FlowTransition

Defined in [`parrot.bots.flows.core.transition`](../summaries/mod:parrot.bots.flows.core.transition.md).

```python
class FlowTransition
```

Conditional edge between two nodes in a flow/crew DAG.

Defines what triggers the transition (``condition``), where it goes
(``targets``), how to prepare the downstream prompt
(``instruction`` / ``prompt_builder``), and optional metadata about
the source node's execution.

Fields:
    source: The ``node_id`` (or agent name) of the originating node.
    targets: Set of ``node_id`` values to activate when this
        transition fires.
    condition: Activation condition (default: ``ON_SUCCESS``).
    instruction: Optional static prompt string for target nodes.
    prompt_builder: Optional async-capable callable
        ``(context, dependencies) -> str`` for dynamic prompts.
    predicate: Required when ``condition == ON_CONDITION``; called
        with the source node's result.  May be async.
    priority: Higher priority transitions are evaluated first.
    metadata: Optional ``NodeExecutionInfo`` attached to this
        transition (replaces ``AgentExecutionInfo`` from the
        original ``parrot.bots.flow.fsm.FlowTransition``).

Example::

    t = FlowTransition(
        source="researcher",
        targets={"writer"},
        condition=TransitionCondition.ON_SUCCESS,
    )
    if await t.should_activate(result="findings"):
        prompt = await t.build_prompt(ctx, deps)

## Methods

- `async def should_activate(self, result: Any, error: Optional[Exception]=None) -> bool` — Determine whether this transition should fire.
- `async def build_prompt(self, context: Any, dependencies: DependencyResults) -> str` — Build the prompt string for target nodes.
