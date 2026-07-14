---
type: Wiki Entity
title: AgentInitializedEvent
id: class:parrot.core.events.lifecycle.events.agent.AgentInitializedEvent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Emitted at the end of AbstractBot.__init__.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# AgentInitializedEvent

Defined in [`parrot.core.events.lifecycle.events.agent`](../summaries/mod:parrot.core.events.lifecycle.events.agent.md).

```python
class AgentInitializedEvent(LifecycleEvent)
```

Emitted at the end of AbstractBot.__init__.

Attributes:
    agent_name: Name of the initialized agent.
    agent_class: Fully-qualified class name of the concrete bot.
