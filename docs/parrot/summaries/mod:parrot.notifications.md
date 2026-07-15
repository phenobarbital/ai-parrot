---
type: Wiki Summary
title: parrot.notifications
id: mod:parrot.notifications
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Notification Mixin for AI-Parrot Agents.
relates_to:
- concept: class:parrot.notifications.FileType
  rel: defines
- concept: class:parrot.notifications.NotificationConfig
  rel: defines
- concept: class:parrot.notifications.NotificationMixin
  rel: defines
- concept: class:parrot.notifications.NotificationProvider
  rel: defines
- concept: mod:parrot.integrations.msteams.graph
  rel: references
---

# `parrot.notifications`

Notification Mixin for AI-Parrot Agents.

Provides notification capabilities to agents using the async-notify library.

## Classes

- **`NotificationProvider(Enum)`** — Supported notification providers.
- **`FileType(Enum)`** — File types for smart handling.
- **`NotificationConfig`** — Configuration for sending notifications.
- **`NotificationMixin`** — Mixin to provide notification capabilities to agents.
