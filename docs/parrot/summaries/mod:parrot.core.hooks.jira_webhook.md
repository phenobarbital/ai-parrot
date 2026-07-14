---
type: Wiki Summary
title: parrot.core.hooks.jira_webhook
id: mod:parrot.core.hooks.jira_webhook
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Jira webhook hook — receives and parses Jira issue events.
relates_to:
- concept: class:parrot.core.hooks.jira_webhook.JiraWebhookHook
  rel: defines
- concept: mod:parrot.core.hooks.base
  rel: references
- concept: mod:parrot.core.hooks.models
  rel: references
---

# `parrot.core.hooks.jira_webhook`

Jira webhook hook — receives and parses Jira issue events.

## Classes

- **`JiraWebhookHook(BaseHook)`** — Receives Jira webhook POST requests via an aiohttp route.
