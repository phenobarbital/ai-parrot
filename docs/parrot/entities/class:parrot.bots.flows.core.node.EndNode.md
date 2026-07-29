---
type: Wiki Entity
title: EndNode
id: class:parrot.bots.flows.core.node.EndNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Virtual exit-point node for flow/crew DAGs.
relates_to:
- concept: class:parrot.bots.flows.core.node.Node
  rel: extends
---

# EndNode

Defined in [`parrot.bots.flows.core.node`](../summaries/mod:parrot.bots.flows.core.node.md).

```python
class EndNode(Node)
```

Virtual exit-point node for flow/crew DAGs.

Marks the successful completion of a DAG flow.  Completes instantly,
returning whatever result is passed to it.

The ``node_id`` doubles as the node's display name (accessed via the
abstract ``name`` property).  Constructors that accept a positional
``name`` string set ``node_id`` to that value.

Args:
    node_id: Node identifier / display name (default: ``'__end__'``).
    metadata: Optional arbitrary metadata dict.

## Methods

- `def name(self) -> str` — Node identifier (same as ``node_id`` for start/end nodes).
- `async def ask(self, question: str='', **ctx: Any) -> str` — No-op execution -- passes the prompt through unchanged.
- `async def execute(self, ctx: Any, deps: Any, **kwargs: Any) -> Any` — Execute end node -- collects final output from dependencies.
- `async def configure(self) -> None` — No-op -- nothing to configure.
