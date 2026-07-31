---
type: Wiki Summary
title: parrot.integrations.whatsapp.wrapper
id: mod:parrot.integrations.whatsapp.wrapper
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: WhatsApp Agent Wrapper.
relates_to:
- concept: class:parrot.integrations.whatsapp.wrapper.WhatsAppAgentWrapper
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.integrations.parser
  rel: references
- concept: mod:parrot.integrations.whatsapp.handler
  rel: references
- concept: mod:parrot.integrations.whatsapp.models
  rel: references
- concept: mod:parrot.integrations.whatsapp.utils
  rel: references
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
---

# `parrot.integrations.whatsapp.wrapper`

WhatsApp Agent Wrapper.

Connects WhatsApp messages to AI-Parrot agents via Meta's Cloud API.
Uses pywa library in custom server mode with aiohttp webhook handlers.

Supports:
- Direct messages (private chats)
- Group messages with @mentions
- Text, image, and document responses
- Per-user conversation memory
- 24-hour messaging window tracking

## Classes

- **`WhatsAppAgentWrapper`** — Wraps an AI-Parrot Agent for WhatsApp integration.
