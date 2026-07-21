---
type: Wiki Summary
title: parrot.core.events.lifecycle.subscribers.logging
id: mod:parrot.core.events.lifecycle.subscribers.logging
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: LoggingSubscriber — logs every LifecycleEvent via the standard logging framework.
relates_to:
- concept: class:parrot.core.events.lifecycle.subscribers.logging.LoggingSubscriber
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
---

# `parrot.core.events.lifecycle.subscribers.logging`

LoggingSubscriber — logs every LifecycleEvent via the standard logging framework.

FEAT-176 — Lifecycle Events System.

``LoggingSubscriber`` is an ``EventProvider`` that subscribes to the
``LifecycleEvent`` base class (which receives every concrete subclass via
isinstance dispatch) and emits a compact single-line log record per event.

## Classes

- **`LoggingSubscriber`** — EventProvider that logs every ``LifecycleEvent`` at a configurable level.
