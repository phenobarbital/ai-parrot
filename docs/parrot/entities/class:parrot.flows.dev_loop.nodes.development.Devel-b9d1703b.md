---
type: Wiki Entity
title: DevelopmentNode
id: class:parrot.flows.dev_loop.nodes.development.DevelopmentNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Third node — dispatches the implementation phase to ``sdd-worker``.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.base.DevLoopNode
  rel: extends
---

# DevelopmentNode

Defined in [`parrot.flows.dev_loop.nodes.development`](../summaries/mod:parrot.flows.dev_loop.nodes.development.md).

```python
class DevelopmentNode(DevLoopNode)
```

Third node — dispatches the implementation phase to ``sdd-worker``.

## Methods

- `async def execute(self, ctx: Union[FlowContext, Dict[str, Any]], deps: Optional[DependencyResults]=None, **kwargs: Any) -> DevelopmentOutput` — Dispatch ``sdd-worker`` inside the upstream worktree.
