---
type: Wiki Summary
title: parrot.core.events.lifecycle.events.invoke
id: mod:parrot.core.events.lifecycle.events.invoke
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Invocation lifecycle events.
relates_to:
- concept: class:parrot.core.events.lifecycle.events.invoke.AfterInvokeEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.invoke.BeforeInvokeEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.invoke.InvokeFailedEvent
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
---

# `parrot.core.events.lifecycle.events.invoke`

Invocation lifecycle events.

FEAT-176 — Lifecycle Events System.

Covers: before/after/failed agent invocations (ask, ask_stream, conversation).

## Classes

- **`BeforeInvokeEvent(LifecycleEvent)`** — Emitted just before an agent invocation begins.
- **`AfterInvokeEvent(LifecycleEvent)`** — Emitted after a successful agent invocation completes.
- **`InvokeFailedEvent(LifecycleEvent)`** — Emitted when an agent invocation raises an unhandled exception.
