---
type: Wiki Entity
title: ToolLike
id: class:parrot.bots.flows.crew.tool_node.ToolLike
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Structural protocol for any object usable as a ToolNode tool.
---

# ToolLike

Defined in [`parrot.bots.flows.crew.tool_node`](../summaries/mod:parrot.bots.flows.crew.tool_node.md).

```python
class ToolLike(Protocol)
```

Structural protocol for any object usable as a ToolNode tool.

Mirrors the ``AgentLike`` pattern from ``flows.core.types``: using a
Protocol (rather than requiring an ``AbstractTool`` subclass) keeps the
node testable with lightweight doubles while every real
``AbstractTool`` satisfies the contract.

Attributes:
    name: Tool identifier.

Methods:
    execute: Async call returning a ``ToolResult``-shaped object.

## Methods

- `async def execute(self, *args: Any, **kwargs: Any) -> Any` — Execute the tool and return a ``ToolResult``.
