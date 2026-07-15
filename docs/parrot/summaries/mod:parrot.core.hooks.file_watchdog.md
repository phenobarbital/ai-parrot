---
type: Wiki Summary
title: parrot.core.hooks.file_watchdog
id: mod:parrot.core.hooks.file_watchdog
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: File watchdog hook — reacts to filesystem changes.
relates_to:
- concept: class:parrot.core.hooks.file_watchdog.FileWatchdogHook
  rel: defines
- concept: mod:parrot.core.hooks.base
  rel: references
- concept: mod:parrot.core.hooks.models
  rel: references
---

# `parrot.core.hooks.file_watchdog`

File watchdog hook — reacts to filesystem changes.

## Classes

- **`FileWatchdogHook(BaseHook)`** — Monitors a directory for file changes and emits HookEvents.
