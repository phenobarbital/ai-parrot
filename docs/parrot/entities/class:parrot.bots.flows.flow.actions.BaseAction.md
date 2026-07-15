---
type: Wiki Entity
title: BaseAction
id: class:parrot.bots.flows.flow.actions.BaseAction
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for all flow lifecycle actions.
---

# BaseAction

Defined in [`parrot.bots.flows.flow.actions`](../summaries/mod:parrot.bots.flows.flow.actions.md).

```python
class BaseAction(ABC)
```

Abstract base class for all flow lifecycle actions.

Actions are executed as pre/post hooks on flow nodes. They receive:
- node_name: The name of the node triggering the action
- payload: For pre-actions this is the prompt, for post-actions the result
- **ctx: Additional context (session_id, user_id, shared_context, etc.)

Subclasses must implement `async def __call__`.
