---
type: Wiki Summary
title: parrot.core.events.lifecycle.events.message
id: mod:parrot.core.events.lifecycle.events.message
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Message lifecycle events.
relates_to:
- concept: class:parrot.core.events.lifecycle.events.message.MessageAddedEvent
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
---

# `parrot.core.events.lifecycle.events.message`

Message lifecycle events.

FEAT-176 — Lifecycle Events System.

Covers: messages entering the agent's conversation history.

## Classes

- **`MessageAddedEvent(LifecycleEvent)`** — Emitted when a message is added to the conversation history.
