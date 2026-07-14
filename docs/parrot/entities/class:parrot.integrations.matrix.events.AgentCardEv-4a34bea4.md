---
type: Wiki Entity
title: AgentCardEventContent
id: class:parrot.integrations.matrix.events.AgentCardEventContent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Content of m.parrot.agent_card state event.
---

# AgentCardEventContent

Defined in [`parrot.integrations.matrix.events`](../summaries/mod:parrot.integrations.matrix.events.md).

```python
class AgentCardEventContent(BaseModel)
```

Content of m.parrot.agent_card state event.

Publishes an agent's A2A card as room state so other
agents/clients can discover it.
