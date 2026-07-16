---
type: Wiki Summary
title: parrot.human.actions.backends.zammad
id: mod:parrot.human.actions.backends.zammad
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Zammad ticket backend using aiohttp.
relates_to:
- concept: class:parrot.human.actions.backends.zammad.ZammadBackend
  rel: defines
- concept: mod:parrot.human.actions.backends.base
  rel: references
- concept: mod:parrot.human.models
  rel: references
---

# `parrot.human.actions.backends.zammad`

Zammad ticket backend using aiohttp.

FEAT-194 — TASK-1275

## Classes

- **`ZammadBackend(ActionBackend)`** — Creates a support ticket in a Zammad instance.
