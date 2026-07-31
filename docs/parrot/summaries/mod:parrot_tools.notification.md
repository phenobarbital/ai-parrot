---
type: Wiki Summary
title: parrot_tools.notification
id: mod:parrot_tools.notification
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: NotificationTool - Send notifications via email, Telegram, Slack, or MS Teams.
relates_to:
- concept: class:parrot_tools.notification.FileType
  rel: defines
- concept: class:parrot_tools.notification.NotificationInput
  rel: defines
- concept: class:parrot_tools.notification.NotificationTool
  rel: defines
- concept: class:parrot_tools.notification.NotificationType
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.notification`

NotificationTool - Send notifications via email, Telegram, Slack, or MS Teams.

A unified tool for LLM agents to send notifications through various channels
using the async-notify library.

## Classes

- **`NotificationType(str, Enum)`** — Supported notification types.
- **`FileType(Enum)`** — File types for smart handling.
- **`NotificationInput(BaseModel)`** — Input schema for notification tool.
- **`NotificationTool(AbstractTool)`** — Unified notification tool for sending messages through multiple channels.
