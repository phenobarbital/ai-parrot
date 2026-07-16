---
type: Wiki Summary
title: parrot.human.actions.backends.webhook
id: mod:parrot.human.actions.backends.webhook
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Generic webhook backend using aiohttp.
relates_to:
- concept: class:parrot.human.actions.backends.webhook.WebhookBackend
  rel: defines
- concept: mod:parrot.human.actions.backends.base
  rel: references
- concept: mod:parrot.human.models
  rel: references
---

# `parrot.human.actions.backends.webhook`

Generic webhook backend using aiohttp.

FEAT-194 — TASK-1275

## Classes

- **`WebhookBackend(ActionBackend)`** — Posts an escalation payload to a configurable webhook endpoint.
