---
type: Wiki Entity
title: StartNode
id: class:parrot.bots.flows.core.node.StartNode
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Virtual entry-point node for flow/crew DAGs.
relates_to:
- concept: class:parrot.bots.flows.core.node.Node
  rel: extends
---

# StartNode

Defined in [`parrot.bots.flows.core.node`](../summaries/mod:parrot.bots.flows.core.node.md).

```python
class StartNode(Node)
```

Virtual entry-point node for flow/crew DAGs.

Carries no agent -- completes instantly and forwards the initial
prompt to all downstream successors.

Duck-typing attributes (``is_configured``, ``configure``, ``ask``)
let engine code treat it uniformly with agent nodes.

The ``node_id`` doubles as the node's display name (accessed via the
abstract ``name`` property).  Constructors that accept a positional
``name`` string set ``node_id`` to that value.

Args:
    node_id: Node identifier / display name (default: ``'__start__'``).
    metadata: Optional arbitrary metadata dict.

## Methods

- `def name(self) -> str` — Node identifier (same as ``node_id`` for start/end nodes).
- `async def ask(self, question: str='', **ctx: Any) -> str` — No-op execution -- passes the prompt through unchanged.
- `async def execute(self, ctx: Any, deps: Any, **kwargs: Any) -> Any` — Execute start node -- forwards initial task from context.
- `async def configure(self) -> None` — No-op -- nothing to configure.
