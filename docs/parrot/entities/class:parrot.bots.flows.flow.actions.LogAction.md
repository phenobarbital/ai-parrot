---
type: Wiki Entity
title: LogAction
id: class:parrot.bots.flows.flow.actions.LogAction
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Log a message with template variables.
---

# LogAction

Defined in [`parrot.bots.flows.flow.actions`](../summaries/mod:parrot.bots.flows.flow.actions.md).

```python
class LogAction(BaseAction)
```

Log a message with template variables.

Template variables:
- {node_name}: Name of the node
- {result}: The payload (result or prompt)
- {prompt}: Alias for payload (for pre-actions)
- Any key from ctx
