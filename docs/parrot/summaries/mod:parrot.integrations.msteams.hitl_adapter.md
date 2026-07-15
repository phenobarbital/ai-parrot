---
type: Wiki Summary
title: parrot.integrations.msteams.hitl_adapter
id: mod:parrot.integrations.msteams.hitl_adapter
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: HITL-dedicated Bot Framework adapter for TeamsHumanChannel.
relates_to:
- concept: class:parrot.integrations.msteams.hitl_adapter.HitlBotConfig
  rel: defines
- concept: class:parrot.integrations.msteams.hitl_adapter.HitlCloudAdapter
  rel: defines
---

# `parrot.integrations.msteams.hitl_adapter`

HITL-dedicated Bot Framework adapter for TeamsHumanChannel.

Vendored / adapted from the azure_teambots private fork's AdapterHandler
pattern (azure_teambots/adapters.py), reusing the same
ConfigurationBotFrameworkAuthentication + BotFrameworkAdapterSettings
construction as the existing Adapter(CloudAdapter) in adapter.py:18.

This module is intentionally isolated — it does not import aiogram and
must never be imported from any Telegram-side module at module level.

## Classes

- **`HitlBotConfig`** — Minimal bot configuration shim for the HITL adapter.
- **`HitlCloudAdapter(CloudAdapter)`** — CloudAdapter configured for the shared HITL bot identity.
