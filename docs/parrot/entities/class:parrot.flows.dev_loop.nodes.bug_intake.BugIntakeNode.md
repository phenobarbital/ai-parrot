---
type: Wiki Entity
title: BugIntakeNode
id: class:parrot.flows.dev_loop.nodes.bug_intake.BugIntakeNode
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Bug-specific intake hook — emits ``flow.bug_brief_validated`` event.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.base.DevLoopNode
  rel: extends
---

# BugIntakeNode

Defined in [`parrot.flows.dev_loop.nodes.bug_intake`](../summaries/mod:parrot.flows.dev_loop.nodes.bug_intake.md).

```python
class BugIntakeNode(DevLoopNode)
```

Bug-specific intake hook — emits ``flow.bug_brief_validated`` event.

FEAT-132 scope-down: universal validation now lives in
:class:`IntentClassifierNode` (which runs before this node on the
bug path). ``BugIntakeNode`` acts as an extension point for future
bug-only enrichment without requiring the flow topology to change.

Args:
    redis_url: Redis URL used to publish ``flow.bug_brief_validated``.
        The connection is lazy: the node is safe to construct without
        a live Redis. The actual publish happens on first ``execute``.
    name: Node id, defaults to ``"bug_intake"``.

## Methods

- `async def execute(self, ctx: Union[FlowContext, Dict[str, Any]], deps: Optional[DependencyResults]=None, **kwargs: Any) -> BugBrief` — Bug-specific intake hook (post FEAT-132 scope-down).
- `async def close(self) -> None` — Release the Redis client connection pool.
