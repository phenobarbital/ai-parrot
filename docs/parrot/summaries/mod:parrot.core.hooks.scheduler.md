---
type: Wiki Summary
title: parrot.core.hooks.scheduler
id: mod:parrot.core.hooks.scheduler
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Scheduler hook — periodic agent triggers via APScheduler.
relates_to:
- concept: class:parrot.core.hooks.scheduler.SchedulerHook
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.core.hooks.base
  rel: references
- concept: mod:parrot.core.hooks.models
  rel: references
---

# `parrot.core.hooks.scheduler`

Scheduler hook — periodic agent triggers via APScheduler.

APScheduler is an optional dependency — install with: pip install ai-parrot[scheduler]

## Classes

- **`SchedulerHook(BaseHook)`** — Periodically fires events using APScheduler (cron or interval).
