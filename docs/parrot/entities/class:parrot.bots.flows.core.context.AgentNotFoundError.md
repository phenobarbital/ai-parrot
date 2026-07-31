---
type: Wiki Entity
title: AgentNotFoundError
id: class:parrot.bots.flows.core.context.AgentNotFoundError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when ``FlowContext.resolve_agent`` cannot find the requested agent.
---

# AgentNotFoundError

Defined in [`parrot.bots.flows.core.context`](../summaries/mod:parrot.bots.flows.core.context.md).

```python
class AgentNotFoundError(LookupError)
```

Raised when ``FlowContext.resolve_agent`` cannot find the requested agent.

Inherits from ``LookupError`` so callers can catch it with either
``except AgentNotFoundError:`` (specific) or ``except LookupError:``
(generic lookup failure).
