---
type: Wiki Summary
title: parrot.core.hooks.github_webhook
id: mod:parrot.core.hooks.github_webhook
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: GitHub webhook hook — receives and parses GitHub pull_request events.
relates_to:
- concept: class:parrot.core.hooks.github_webhook.GitHubWebhookHook
  rel: defines
- concept: mod:parrot.core.hooks.base
  rel: references
- concept: mod:parrot.core.hooks.models
  rel: references
---

# `parrot.core.hooks.github_webhook`

GitHub webhook hook — receives and parses GitHub pull_request events.

## Classes

- **`GitHubWebhookHook(BaseHook)`** — Receives GitHub webhook POST requests via an aiohttp route.
