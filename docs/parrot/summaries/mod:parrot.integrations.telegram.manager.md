---
type: Wiki Summary
title: parrot.integrations.telegram.manager
id: mod:parrot.integrations.telegram.manager
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Telegram Bot Manager.
relates_to:
- concept: class:parrot.integrations.telegram.manager.TelegramBotManager
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.integrations.telegram.decorators
  rel: references
- concept: mod:parrot.integrations.telegram.models
  rel: references
- concept: mod:parrot.integrations.telegram.wrapper
  rel: references
- concept: mod:parrot.manager
  rel: references
---

# `parrot.integrations.telegram.manager`

Telegram Bot Manager.

Manages lifecycle of Telegram bots exposing AI-Parrot agents.
Loads configuration from {ENV_DIR}/telegram_bots.yaml and starts
aiogram polling for each configured bot.

## Classes

- **`TelegramBotManager`** — Manages Telegram bot lifecycle for exposed agents.
