---
type: Wiki Entity
title: AgentCard
id: class:parrot.integrations.telegram.crew.agent_card.AgentCard
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Identity and capability descriptor for an agent in the crew.
---

# AgentCard

Defined in [`parrot.integrations.telegram.crew.agent_card`](../summaries/mod:parrot.integrations.telegram.crew.agent_card.md).

```python
class AgentCard(BaseModel)
```

Identity and capability descriptor for an agent in the crew.

## Methods

- `def to_telegram_text(self) -> str` — Render a formatted announcement message for the Telegram group.
- `def to_registry_line(self) -> str` — Render a compact one-line status for the pinned registry message.
