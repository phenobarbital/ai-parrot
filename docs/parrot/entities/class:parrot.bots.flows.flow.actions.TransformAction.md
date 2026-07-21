---
type: Wiki Entity
title: TransformAction
id: class:parrot.bots.flows.flow.actions.TransformAction
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Transform the result using a safe expression.
---

# TransformAction

Defined in [`parrot.bots.flows.flow.actions`](../summaries/mod:parrot.bots.flows.flow.actions.md).

```python
class TransformAction(BaseAction)
```

Transform the result using a safe expression.

Supports simple transformations like:
- "result.lower()" - call method on result
- "result.strip()" - call method
- "result.upper()" - call method

NOTE: This uses safe attribute access only, NOT eval().
Complex transformations should use a proper expression language (CEL).
