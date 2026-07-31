---
type: Wiki Summary
title: parrot.core.hooks.messaging
id: mod:parrot.core.hooks.messaging
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Messaging platform hooks — Telegram, WhatsApp, MS Teams.
relates_to:
- concept: class:parrot.core.hooks.messaging.MSTeamsHook
  rel: defines
- concept: class:parrot.core.hooks.messaging.TelegramHook
  rel: defines
- concept: class:parrot.core.hooks.messaging.WhatsAppHook
  rel: defines
- concept: mod:parrot.core.hooks.base
  rel: references
- concept: mod:parrot.core.hooks.models
  rel: references
---

# `parrot.core.hooks.messaging`

Messaging platform hooks — Telegram, WhatsApp, MS Teams.

These hooks register aiohttp routes that receive incoming messages from
messaging platforms and re-emit them as ``HookEvent`` objects.  They
are designed to work alongside (not replace) the full integration
wrappers in ``parrot/integrations/``.

The wrapper classes handle bidirectional communication (receive + respond).
These hooks only handle the *trigger* side — when a message arrives,
they fire a ``HookEvent`` so the orchestrator can route it to an agent.

## Classes

- **`TelegramHook(_MessagingHookBase)`** — Receives Telegram messages via webhook and fires HookEvents.
- **`WhatsAppHook(_MessagingHookBase)`** — Receives WhatsApp webhook POSTs from Meta Cloud API.
- **`MSTeamsHook(_MessagingHookBase)`** — Receives MS Teams Activity POSTs via Bot Framework webhook.
