---
type: Wiki Entity
title: DevLoopCloseNode
id: class:parrot.flows.dev_loop.nodes.close.DevLoopCloseNode
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Terminal node — Jira summary comment + transition, then end the flow.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.base.DevLoopNode
  rel: extends
---

# DevLoopCloseNode

Defined in [`parrot.flows.dev_loop.nodes.close`](../summaries/mod:parrot.flows.dev_loop.nodes.close.md).

```python
class DevLoopCloseNode(DevLoopNode)
```

Terminal node — Jira summary comment + transition, then end the flow.

## Methods

- `async def execute(self, ctx: Union[FlowContext, Dict[str, Any]], deps: Optional[DependencyResults]=None, **kwargs: Any) -> Dict[str, str]` — Record the run's final state on Jira. Never raises.
