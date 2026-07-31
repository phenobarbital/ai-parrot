---
type: Wiki Summary
title: parrot.integrations.telegram.crew.transport
id: mod:parrot.integrations.telegram.crew.transport
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: TelegramCrewTransport — top-level orchestrator for multi-agent crew.
relates_to:
- concept: class:parrot.integrations.telegram.crew.transport.TelegramCrewTransport
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.integrations.telegram.crew.agent_card
  rel: references
- concept: mod:parrot.integrations.telegram.crew.config
  rel: references
- concept: mod:parrot.integrations.telegram.crew.coordinator
  rel: references
- concept: mod:parrot.integrations.telegram.crew.crew_wrapper
  rel: references
- concept: mod:parrot.integrations.telegram.crew.mention
  rel: references
- concept: mod:parrot.integrations.telegram.crew.payload
  rel: references
- concept: mod:parrot.integrations.telegram.crew.registry
  rel: references
---

# `parrot.integrations.telegram.crew.transport`

TelegramCrewTransport — top-level orchestrator for multi-agent crew.

Manages the full lifecycle of a multi-agent crew in a Telegram supergroup:
coordinator bot startup, agent wrapper creation, agent registration,
aiogram polling, and graceful shutdown.

Usage::

    config = TelegramCrewConfig.from_yaml("crew.yaml")
    async with TelegramCrewTransport(config) as transport:
        # transport is running — agents respond to @mentions
        await asyncio.Event().wait()  # or your application loop

## Classes

- **`TelegramCrewTransport`** — Orchestrator for a multi-agent crew in a Telegram supergroup.
