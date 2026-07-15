---
type: Wiki Entity
title: IntentClassifierNode
id: class:parrot.flows.dev_loop.nodes.intent_classifier.IntentClassifierNode
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Validates a :class:`WorkBrief` and routes by ``kind``.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.base.DevLoopNode
  rel: extends
---

# IntentClassifierNode

Defined in [`parrot.flows.dev_loop.nodes.intent_classifier`](../summaries/mod:parrot.flows.dev_loop.nodes.intent_classifier.md).

```python
class IntentClassifierNode(DevLoopNode)
```

Validates a :class:`WorkBrief` and routes by ``kind``.

This is the first node in the FEAT-132 flow topology. It replaces
the universal validation that previously ran inside ``BugIntakeNode``
so that non-bug kinds (enhancement, new_feature) also receive the
allowlist / path-traversal guards before reaching ``ResearchNode``.

Args:
    redis_url: Redis URL used to publish ``flow.intake_validated``.
        The connection is lazy: the node is safe to construct without
        a live Redis instance. The publish happens on first ``execute``.
    name: Node identifier, defaults to ``"intent_classifier"``.

## Methods

- `async def execute(self, ctx: Union[FlowContext, Dict[str, Any]], deps: Optional[DependencyResults]=None, **kwargs: Any) -> WorkBrief` — Validate the :class:`WorkBrief` and emit the intake event.
- `async def close(self) -> None` — Release the Redis client connection pool.
