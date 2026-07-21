---
type: Wiki Summary
title: parrot.human.events
id: mod:parrot.human.events
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Structured event models for HITL multi-tier escalation tier transitions.
relates_to:
- concept: class:parrot.human.events.HitlChainExhaustedEvent
  rel: defines
- concept: class:parrot.human.events.HitlTierActionExecutedEvent
  rel: defines
- concept: class:parrot.human.events.HitlTierActionFailedEvent
  rel: defines
- concept: class:parrot.human.events.HitlTierAdvancedEvent
  rel: defines
- concept: class:parrot.human.events.HitlTierEnteredEvent
  rel: defines
---

# `parrot.human.events`

Structured event models for HITL multi-tier escalation tier transitions.

Provides Pydantic event models emitted by :class:`~parrot.human.manager.HumanInteractionManager`
on every tier-transition decision.  Subscribers register via the
``on_event`` constructor kwarg on the manager.

Design decision (TASK-1280): the **hook pattern** was chosen over
``EventEmitterMixin`` inheritance.  The existing ``EventRegistry.emit()``
expects a ``LifecycleEvent`` (frozen dataclass) with ``TraceContext``,
``source_type``, etc. — a different base type than the Pydantic models
specified here.  Wiring the manager into that hierarchy would require
non-trivial MRO changes and couples HITL to the lifecycle-events
infrastructure unnecessarily.  The ``on_event`` hook is simpler, test-friendly,
and keeps HITL self-contained.

Event name strings use dot-namespaced convention:
- ``"hitl.tier.entered"``   — ``HitlTierEnteredEvent``
- ``"hitl.tier.advanced"``  — ``HitlTierAdvancedEvent``
- ``"hitl.tier.action_executed"`` — ``HitlTierActionExecutedEvent``
- ``"hitl.tier.action_failed"``   — ``HitlTierActionFailedEvent``
- ``"hitl.chain.exhausted"`` — ``HitlChainExhaustedEvent``

FEAT-194 — TASK-1280

## Classes

- **`HitlTierEnteredEvent(BaseModel)`** — Emitted when the escalation cursor enters a tier for the first time.
- **`HitlTierAdvancedEvent(BaseModel)`** — Emitted when the escalation cursor moves from one tier to another.
- **`HitlTierActionExecutedEvent(BaseModel)`** — Emitted after a NOTIFY or TICKET action completes successfully.
- **`HitlTierActionFailedEvent(BaseModel)`** — Emitted when an action raises an exception or returns ``error=True``.
- **`HitlChainExhaustedEvent(BaseModel)`** — Emitted when the escalation chain terminates after exhausting all tiers.
