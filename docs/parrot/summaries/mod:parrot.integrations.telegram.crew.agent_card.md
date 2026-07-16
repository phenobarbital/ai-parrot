---
type: Wiki Summary
title: parrot.integrations.telegram.crew.agent_card
id: mod:parrot.integrations.telegram.crew.agent_card
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AgentCard and AgentSkill models for TelegramCrewTransport.
relates_to:
- concept: class:parrot.integrations.telegram.crew.agent_card.AgentCard
  rel: defines
- concept: class:parrot.integrations.telegram.crew.agent_card.AgentSkill
  rel: defines
---

# `parrot.integrations.telegram.crew.agent_card`

AgentCard and AgentSkill models for TelegramCrewTransport.

These Pydantic models describe an agent's identity, capabilities,
and status within a crew. They provide rendering methods for
Telegram-formatted announcements and pinned registry lines.

## Classes

- **`AgentSkill(BaseModel)`** — Describes a single capability of an agent.
- **`AgentCard(BaseModel)`** — Identity and capability descriptor for an agent in the crew.
