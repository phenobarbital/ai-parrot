---
type: Wiki Summary
title: parrot.core.events.lifecycle.meta
id: mod:parrot.core.events.lifecycle.meta
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Meta-events for error isolation (model B).
relates_to:
- concept: class:parrot.core.events.lifecycle.meta.SubscriberErrorEvent
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
---

# `parrot.core.events.lifecycle.meta`

Meta-events for error isolation (model B).

FEAT-176 — Lifecycle Events System.

Meta-events are emitted BY the EventRegistry, not by domain code.
They report internal system conditions (subscriber failures, etc.).

## Classes

- **`SubscriberErrorEvent(LifecycleEvent)`** — Emitted to the global registry when a subscriber raises.
