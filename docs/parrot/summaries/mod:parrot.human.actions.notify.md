---
type: Wiki Summary
title: parrot.human.actions.notify
id: mod:parrot.human.actions.notify
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Escalation action that sends a one-way notification.
relates_to:
- concept: class:parrot.human.actions.notify.NotifyAction
  rel: defines
- concept: mod:parrot.human.actions.backends
  rel: references
- concept: mod:parrot.human.actions.base
  rel: references
---

# `parrot.human.actions.notify`

Escalation action that sends a one-way notification.

Dispatches by ``tier.action_metadata["kind"]`` to the appropriate backend.
Supports legacy ``action_metadata["channel"]`` key for backwards compatibility.

FEAT-194 — TASK-1276

## Classes

- **`NotifyAction(EscalationAction)`** — Dispatches one-way escalation notifications to a backend.
