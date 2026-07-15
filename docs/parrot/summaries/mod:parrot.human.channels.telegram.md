---
type: Wiki Summary
title: parrot.human.channels.telegram
id: mod:parrot.human.channels.telegram
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Telegram Human Channel for AI-Parrot HITL.
relates_to:
- concept: class:parrot.human.channels.telegram.TelegramHumanChannel
  rel: defines
- concept: mod:parrot.human.channels
  rel: references
- concept: mod:parrot.human.channels.base
  rel: references
- concept: mod:parrot.human.models
  rel: references
- concept: mod:parrot.voice.transcriber
  rel: references
---

# `parrot.human.channels.telegram`

Telegram Human Channel for AI-Parrot HITL.

Uses aiogram v3 to send interactive messages (inline keyboards, polls)
to humans via Telegram private chat, and captures responses through
callback queries.

Security:
- All interactions are point-to-point (private chat only).
- Callback buttons use secure tokens (not raw interaction IDs).
- Tokens are single-use and bound to a specific human + interaction.
- Respondent identity is verified against the interaction's target_humans.

This channel is designed to work alongside the existing Telegram
integration (TelegramBotManager / TelegramAgentWrapper). It can
share the same aiogram Bot instance or use a dedicated one for HITL.

Usage:
    from aiogram import Bot
    bot = Bot(token="YOUR_BOT_TOKEN")
    channel = TelegramHumanChannel(bot=bot, redis=redis_client)
    await channel.register_response_handler(manager.receive_response)

## Classes

- **`TelegramHumanChannel(HumanChannel)`** — Telegram channel for Human-in-the-Loop interactions.
