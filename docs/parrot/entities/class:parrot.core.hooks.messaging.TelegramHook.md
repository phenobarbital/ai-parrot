---
type: Wiki Entity
title: TelegramHook
id: class:parrot.core.hooks.messaging.TelegramHook
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Receives Telegram messages via webhook and fires HookEvents.
---

# TelegramHook

Defined in [`parrot.core.hooks.messaging`](../summaries/mod:parrot.core.hooks.messaging.md).

```python
class TelegramHook(_MessagingHookBase)
```

Receives Telegram messages via webhook and fires HookEvents.

Works alongside ``TelegramAgentWrapper``.  When a message matches
the configured filters, a ``HookEvent`` is emitted so the
orchestrator can route it to an agent or crew.

## Methods

- `def setup_routes(self, app: Any) -> None`
