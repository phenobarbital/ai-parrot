---
type: Wiki Summary
title: parrot.human.actions.ticket
id: mod:parrot.human.actions.ticket
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Escalation action that opens a ticket in an external system.
relates_to:
- concept: class:parrot.human.actions.ticket.TicketAction
  rel: defines
- concept: mod:parrot.human.actions.backends
  rel: references
- concept: mod:parrot.human.actions.base
  rel: references
---

# `parrot.human.actions.ticket`

Escalation action that opens a ticket in an external system.

Dispatches by ``tier.action_metadata["kind"]`` (or legacy ``"platform"``).
Supports Zammad in V1.

FEAT-194 — TASK-1276

## Classes

- **`TicketAction(EscalationAction)`** — Dispatches ticket-creation escalation actions to Zammad (V1).
