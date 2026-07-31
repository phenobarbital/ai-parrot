---
type: Wiki Summary
title: parrot.services.heartbeat
id: mod:parrot.services.heartbeat
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Heartbeat scheduler for periodic agent wake-ups.
relates_to:
- concept: class:parrot.services.heartbeat.HeartbeatScheduler
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.services.models
  rel: references
---

# `parrot.services.heartbeat`

Heartbeat scheduler for periodic agent wake-ups.

APScheduler is an optional dependency — install with: pip install ai-parrot[scheduler]

## Classes

- **`HeartbeatScheduler`** — Schedules periodic agent heartbeats via APScheduler.
