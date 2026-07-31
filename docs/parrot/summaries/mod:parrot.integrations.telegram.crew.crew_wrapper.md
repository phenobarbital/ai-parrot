---
type: Wiki Summary
title: parrot.integrations.telegram.crew.crew_wrapper
id: mod:parrot.integrations.telegram.crew.crew_wrapper
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CrewAgentWrapper — per-agent message handler for crew context.
relates_to:
- concept: class:parrot.integrations.telegram.crew.crew_wrapper.CrewAgentWrapper
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.integrations.parser
  rel: references
- concept: mod:parrot.integrations.telegram.crew.agent_card
  rel: references
- concept: mod:parrot.integrations.telegram.crew.coordinator
  rel: references
- concept: mod:parrot.integrations.telegram.crew.mention
  rel: references
- concept: mod:parrot.integrations.telegram.crew.payload
  rel: references
- concept: mod:parrot.integrations.telegram.filters
  rel: references
- concept: mod:parrot.integrations.telegram.utils
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
---

# `parrot.integrations.telegram.crew.crew_wrapper`

CrewAgentWrapper — per-agent message handler for crew context.

Bridges an AI-Parrot agent with the Telegram crew protocol.
Handles @mention routing, silent tool call execution, @mention-tagged
responses, document send/receive, typing indicators, and status
updates to the coordinator.

Uses composition (NOT inheritance) from TelegramAgentWrapper.

## Classes

- **`CrewAgentWrapper`** — Per-agent wrapper that handles @mention messages in a crew supergroup.
