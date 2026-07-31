---
type: Wiki Entity
title: DevLoopNode
id: class:parrot.flows.dev_loop.nodes.base.DevLoopNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Base node for the dev-loop flow (FEAT-129 / FEAT-132).
relates_to:
- concept: class:parrot.bots.flows.core.node.Node
  rel: extends
---

# DevLoopNode

Defined in [`parrot.flows.dev_loop.nodes.base`](../summaries/mod:parrot.flows.dev_loop.nodes.base.md).

```python
class DevLoopNode(Node)
```

Base node for the dev-loop flow (FEAT-129 / FEAT-132).

Subclasses implement ``execute(ctx, deps, **kwargs)`` and use
:meth:`shared_state` to read/write cross-node payloads.

Args:
    node_id: Unique identifier within the flow graph.
    dependencies: Upstream node_ids (optional — ``AgentsFlow`` derives
        them from the edge list in explicit-edge mode).
    successors: Downstream node_ids (optional, same reason).
    fsm: Per-run task FSM; auto-created when ``None``.

## Methods

- `def model_post_init(self, __context: Any) -> None` — Auto-create the FSM; initialise the base logger.
- `def name(self) -> str` — Node identifier used by the flow router.
- `def shared_state(ctx: Union[FlowContext, Dict[str, Any]]) -> Dict[str, Any]` — Return the mutable cross-node state dict for *ctx*.
- `def initial_prompt(ctx: Union[FlowContext, Dict[str, Any]]) -> str` — Return the run's initial task/prompt string.
