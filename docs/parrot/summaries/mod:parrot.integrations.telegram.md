---
type: Wiki Summary
title: parrot.integrations.telegram
id: mod:parrot.integrations.telegram
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Telegram Integration for AI-Parrot Agents.
relates_to:
- concept: mod:parrot.integrations
  rel: references
- concept: mod:parrot.integrations.manager
  rel: references
- concept: mod:parrot.integrations.models
  rel: references
- concept: mod:parrot.integrations.utils
  rel: references
---

# `parrot.integrations.telegram`

Telegram Integration for AI-Parrot Agents.

Provides Telegram bot functionality using aiogram v3 to expose
agents, crews, and flows via Telegram messaging.

Supports:
- Direct messages (private chats)
- Group messages with @mentions
- Group commands (/ask)
- Channel posts (optional)

Example YAML configuration (env/telegram_bots.yaml):

    agents:
      HRAgent:
        chatbot_id: hr_agent
        welcome_message: "Hello! I'm your HR Assistant."
        enable_group_mentions: true
        enable_group_commands: true
        reply_in_thread: true
        # bot_token: optional - defaults to HRAGENT_TELEGRAM_TOKEN env var
