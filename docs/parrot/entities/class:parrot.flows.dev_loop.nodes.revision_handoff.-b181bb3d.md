---
type: Wiki Entity
title: RevisionHandoffNode
id: class:parrot.flows.dev_loop.nodes.revision_handoff.RevisionHandoffNode
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Revision-path handoff — push existing branch + comment existing PR.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.base.DevLoopNode
  rel: extends
---

# RevisionHandoffNode

Defined in [`parrot.flows.dev_loop.nodes.revision_handoff`](../summaries/mod:parrot.flows.dev_loop.nodes.revision_handoff.md).

```python
class RevisionHandoffNode(DevLoopNode)
```

Revision-path handoff — push existing branch + comment existing PR.

## Methods

- `async def execute(self, ctx: Union[FlowContext, Dict[str, Any]], deps: Optional[DependencyResults]=None, **kwargs: Any) -> Dict[str, Any]` — Push the revised branch and comment on the same PR. Never raises.
