---
type: Wiki Summary
title: parrot.integrations.msagentsdk.agent
id: mod:parrot.integrations.msagentsdk.agent
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Bridge between ai-parrot AbstractBot and the Microsoft 365 Agents SDK protocol.
relates_to:
- concept: class:parrot.integrations.msagentsdk.agent.ParrotM365Agent
  rel: defines
- concept: func:parrot.integrations.msagentsdk.agent.render_reply_text
  rel: defines
- concept: mod:parrot.auth.broker
  rel: references
- concept: mod:parrot.auth.context
  rel: references
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.auth.identity
  rel: references
- concept: mod:parrot.auth.permission
  rel: references
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.human.suspended_store
  rel: references
- concept: mod:parrot.integrations.msagentsdk
  rel: references
- concept: mod:parrot.integrations.msagentsdk.auth
  rel: references
- concept: mod:parrot.integrations.msagentsdk.cards
  rel: references
- concept: mod:parrot.integrations.msagentsdk.resume
  rel: references
- concept: mod:parrot.integrations.msagentsdk.semantic
  rel: references
- concept: mod:parrot.utils.helpers
  rel: references
---

# `parrot.integrations.msagentsdk.agent`

Bridge between ai-parrot AbstractBot and the Microsoft 365 Agents SDK protocol.

## Classes

- **`ParrotM365Agent`** — Bridges ai-parrot AbstractBot to the Microsoft 365 Agent protocol.

## Functions

- `def render_reply_text(response: Any) -> str` — Produce human-readable reply text from an ``AIMessage``.
