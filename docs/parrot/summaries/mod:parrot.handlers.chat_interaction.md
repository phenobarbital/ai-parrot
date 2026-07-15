---
type: Wiki Summary
title: parrot.handlers.chat_interaction
id: mod:parrot.handlers.chat_interaction
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: REST handler for chat interaction persistence.
relates_to:
- concept: class:parrot.handlers.chat_interaction.ChatInteractionHandler
  rel: defines
---

# `parrot.handlers.chat_interaction`

REST handler for chat interaction persistence.

Provides endpoints to list, load, and delete chat conversations
stored via ChatStorage (Redis + DocumentDB).

## Classes

- **`ChatInteractionHandler(BaseView)`** — Manage persisted chat interactions.
