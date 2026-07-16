---
type: Wiki Entity
title: Node
id: class:parrot.bots.flows.core.node.Node
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base for all flow/crew nodes (frozen Pydantic).
---

# Node

Defined in [`parrot.bots.flows.core.node`](../summaries/mod:parrot.bots.flows.core.node.md).

```python
class Node(BaseModel)
```

Abstract base for all flow/crew nodes (frozen Pydantic).

Extends the pattern in ``parrot.bots.flow.node.Node`` by adding a
``node_id`` field so each graph instance can be uniquely addressed
independently from the underlying agent's name.

Frozen-model contract:
- ``node.field = value`` raises ``ValidationError`` (Pydantic v2 frozen).
- ``node._pre_actions.append(cb)`` is allowed (mutating list, not
  reassigning the private attr).
- Nested object mutation (e.g., ``node.fsm.start()``) is allowed because
  the ``fsm`` field itself is not being reassigned.

Subclasses must implement the abstract ``name`` property.

Pre-actions receive ``(node_name, prompt, **ctx)`` and run before the
node executes.  Post-actions receive ``(node_name, result, **ctx)`` and
run after execution.

Example::

    class MyNode(Node):
        my_field: str

        @property
        def name(self) -> str:
            return self.my_field

## Methods

- `def model_post_init(self, __context: Any) -> None` — Initialise private attrs that require post-construction logic.
- `def name(self) -> str` — Human-readable agent/node name.
- `def logger(self) -> logging.Logger` — Per-node logger (lazy-initialised in model_post_init).
- `def add_pre_action(self, action: ActionCallback) -> None` — Register a callback to run before node execution.
- `def add_post_action(self, action: ActionCallback) -> None` — Register a callback to run after node execution.
- `async def run_pre_actions(self, prompt: str='', **ctx: Any) -> None` — Execute all registered pre-actions in order.
- `async def run_post_actions(self, result: Any=None, **ctx: Any) -> None` — Execute all registered post-actions in order.
