---
type: Wiki Summary
title: parrot.integrations.slack.socket_handler
id: mod:parrot.integrations.slack.socket_handler
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Socket Mode handler for Slack integration.
relates_to:
- concept: class:parrot.integrations.slack.socket_handler.SlackSocketHandler
  rel: defines
- concept: mod:parrot.integrations.slack.wrapper
  rel: references
---

# `parrot.integrations.slack.socket_handler`

Socket Mode handler for Slack integration.

Allows Slack integration without public webhook URLs by using WebSocket connections.
Recommended for: local development, environments behind firewalls.
For production, prefer webhook mode.

## Classes

- **`SlackSocketHandler`** — Handle Slack events via Socket Mode (WebSocket connection).
