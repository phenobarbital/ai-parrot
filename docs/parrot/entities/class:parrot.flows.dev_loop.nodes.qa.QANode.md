---
type: Wiki Entity
title: QANode
id: class:parrot.flows.dev_loop.nodes.qa.QANode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Fourth node — runs deterministic acceptance verification.
relates_to:
- concept: class:parrot.flows.dev_loop.nodes.base.DevLoopNode
  rel: extends
---

# QANode

Defined in [`parrot.flows.dev_loop.nodes.qa`](../summaries/mod:parrot.flows.dev_loop.nodes.qa.md).

```python
class QANode(DevLoopNode)
```

Fourth node — runs deterministic acceptance verification.

## Methods

- `async def execute(self, ctx: Union[FlowContext, Dict[str, Any]], deps: Optional[DependencyResults]=None, **kwargs: Any) -> QAReport` — Dispatch ``sdd-qa`` and return the :class:`QAReport`.
