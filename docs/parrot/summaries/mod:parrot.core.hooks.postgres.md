---
type: Wiki Summary
title: parrot.core.hooks.postgres
id: mod:parrot.core.hooks.postgres
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: PostgreSQL LISTEN/NOTIFY hook.
relates_to:
- concept: class:parrot.core.hooks.postgres.PostgresListenHook
  rel: defines
- concept: mod:parrot.core.hooks.base
  rel: references
- concept: mod:parrot.core.hooks.models
  rel: references
---

# `parrot.core.hooks.postgres`

PostgreSQL LISTEN/NOTIFY hook.

## Classes

- **`PostgresListenHook(BaseHook)`** — Listens to a PostgreSQL channel via LISTEN/NOTIFY and emits HookEvents.
