---
type: Wiki Summary
title: parrot.integrations.telegram.crew
id: mod:parrot.integrations.telegram.crew
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Telegram Crew Transport — multi-agent crew in a Telegram supergroup.
relates_to:
- concept: mod:parrot.integrations.telegram
  rel: references
---

# `parrot.integrations.telegram.crew`

Telegram Crew Transport — multi-agent crew in a Telegram supergroup.

Provides all public types for configuring and running a crew of AI agents
that communicate via @mentions in a shared Telegram supergroup, managed
by a coordinator bot with a pinned registry message.

Usage::

    from parrot.integrations.telegram.crew import (
        TelegramCrewTransport,
        TelegramCrewConfig,
    )

    config = TelegramCrewConfig.from_yaml("crew.yaml")
    async with TelegramCrewTransport(config) as transport:
        await asyncio.Event().wait()
