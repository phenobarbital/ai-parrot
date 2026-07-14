---
type: Wiki Entity
title: AgentNode
id: class:parrot.bots.flows.core.node.AgentNode
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A graph node that wraps an ``AgentLike`` agent and an FSM.
relates_to:
- concept: class:parrot.bots.flows.core.node.Node
  rel: extends
---

# AgentNode

Defined in [`parrot.bots.flows.core.node`](../summaries/mod:parrot.bots.flows.core.node.md).

```python
class AgentNode(Node)
```

A graph node that wraps an ``AgentLike`` agent and an FSM.

``node_id`` is unique per graph instance (e.g., ``"researcher-1"``).
``name`` delegates to the wrapped agent (e.g., ``"researcher"``).

The embedded ``AgentTaskMachine`` tracks this node's execution
lifecycle (idle -> ready -> running -> completed/failed).

**FEAT-163 execute signature change:**

The old signature ``execute(prompt, *, timeout, **ctx)`` has been
replaced with ``execute(ctx, deps, **kwargs)`` where:

- ``ctx``: ``FlowContext`` -- the running flow's execution state.
- ``deps``: ``DependencyResults`` -- mapping of dep node_id -> result.
- ``**kwargs``: forwarded to ``agent.ask()``.

Prompt derivation now lives in the overridable ``_build_prompt(ctx, deps)``
method.  The default reads ``ctx.get_input_for_agent(self.agent.name,
self.dependencies)`` and returns it as a string.

**FSM lifecycle is managed by the scheduler (AgentsFlow.run_flow), NOT
inside execute().**  Do not call ``self.fsm.start()`` / ``.succeed()`` /
``.fail()`` here.

Args:
    agent: The agent object conforming to ``AgentLike``.
    node_id: Unique identifier for this node instance in the DAG.
    dependencies: Set of ``node_id`` values that must complete first.
    successors: Set of ``node_id`` values triggered after this node.
    fsm: Optional pre-constructed FSM (auto-created in model_post_init
         when ``None``).

## Methods

- `def model_post_init(self, __context: Any) -> None` — Auto-create the FSM if not provided; initialise logger.
- `def name(self) -> str` — Agent identity (delegates to ``agent.name``).
- `async def execute(self, ctx: 'FlowContext', deps: DependencyResults, **kwargs: Any) -> Any` — Execute the agent with pre/post hooks.
