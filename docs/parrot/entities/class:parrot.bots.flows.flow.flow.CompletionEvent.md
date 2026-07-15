---
type: Wiki Entity
title: CompletionEvent
id: class:parrot.bots.flows.flow.flow.CompletionEvent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Event pushed to the scheduler's completion queue when a node finishes.
---

# CompletionEvent

Defined in [`parrot.bots.flows.flow.flow`](../summaries/mod:parrot.bots.flows.flow.flow.md).

```python
class CompletionEvent
```

Event pushed to the scheduler's completion queue when a node finishes.

Attributes:
    node_id: Identifier of the node that finished.
    result: The result value returned by the node (``None`` on error).
    error: The exception raised by the node (``None`` on success).
