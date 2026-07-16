---
type: Wiki Summary
title: parrot.integrations.telegram.crew.config
id: mod:parrot.integrations.telegram.crew.config
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration models for TelegramCrewTransport.
relates_to:
- concept: class:parrot.integrations.telegram.crew.config.CrewAgentEntry
  rel: defines
- concept: class:parrot.integrations.telegram.crew.config.TelegramCrewConfig
  rel: defines
---

# `parrot.integrations.telegram.crew.config`

Configuration models for TelegramCrewTransport.

Pydantic v2 models for configuring a multi-agent crew
in a Telegram supergroup.

## Classes

- **`CrewAgentEntry(BaseModel)`** — Configuration for a single agent in the crew.
- **`TelegramCrewConfig(BaseModel)`** — Root configuration for a multi-agent crew in a Telegram supergroup.
