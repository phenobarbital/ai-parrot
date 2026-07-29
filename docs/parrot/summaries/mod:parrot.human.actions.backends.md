---
type: Wiki Summary
title: parrot.human.actions.backends
id: mod:parrot.human.actions.backends
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Concrete action backends for the HITL escalation system.
relates_to:
- concept: mod:parrot.human
  rel: references
- concept: mod:parrot.human.actions.base
  rel: references
---

# `parrot.human.actions.backends`

Concrete action backends for the HITL escalation system.

FEAT-194 — TASK-1275

Each backend implements :class:`~parrot.human.actions.backends.base.ActionBackend`
and is dispatched by :class:`~parrot.human.actions.notify.NotifyAction` or
:class:`~parrot.human.actions.ticket.TicketAction` based on
``tier.action_metadata["kind"]``.
