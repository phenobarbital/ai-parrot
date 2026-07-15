---
type: Wiki Entity
title: FailureHandlerNode
id: class:parrot.flows.dev_loop.nodes.failure_handler.FailureHandlerNode
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Terminal failure node — comment + transition + reassign on Jira.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.base.DevLoopNode
  rel: extends
---

# FailureHandlerNode

Defined in [`parrot.flows.dev_loop.nodes.failure_handler`](../summaries/mod:parrot.flows.dev_loop.nodes.failure_handler.md).

```python
class FailureHandlerNode(DevLoopNode)
```

Terminal failure node — comment + transition + reassign on Jira.

## Methods

- `async def execute(self, ctx: Union[FlowContext, Dict[str, Any]], deps: Optional[DependencyResults]=None, **kwargs: Any) -> Dict[str, str]` — Escalate the run to a human via Jira. Never raises.
