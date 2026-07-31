---
type: Wiki Summary
title: parrot.core.events.lifecycle.registry
id: mod:parrot.core.events.lifecycle.registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'EventRegistry: typed lifecycle event dispatch with error isolation.'
relates_to:
- concept: class:parrot.core.events.lifecycle.registry.EventRegistry
  rel: defines
- concept: mod:parrot.core.events.evb
  rel: references
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: references
- concept: mod:parrot.core.events.lifecycle.meta
  rel: references
- concept: mod:parrot.core.events.lifecycle.provider
  rel: references
---

# `parrot.core.events.lifecycle.registry`

EventRegistry: typed lifecycle event dispatch with error isolation.

FEAT-176 — Lifecycle Events System.

This module provides the ``EventRegistry`` class — the central dispatch engine
for typed ``LifecycleEvent`` instances.  Key properties:

- **isinstance-based matching**: subscribing to ``LifecycleEvent`` receives
  every concrete event; subscribing to ``BeforeToolCallEvent`` receives only
  that subtype.
- **Deterministic ordering**: ``Before*`` events fire subscribers in
  FORWARD registration order (setup); ``After*`` and ``*Failed`` events fire
  subscribers in REVERSE registration order (cleanup symmetry).
- **Error isolation (model B)**: subscriber exceptions are caught, logged,
  and emitted as ``SubscriberErrorEvent`` to the global registry. The agent
  flow is NEVER interrupted by a subscriber failure.
- **Per-subscriber dual-emit opt-in**: set ``forward_to_bus=True`` on a
  subscription to also push the event payload to ``EventBus``.  Note:
  ``ClientStreamChunkEvent`` is never auto-forwarded — the per-subscriber
  flag is the only forwarding mechanism, which avoids bus pressure on high-
  frequency streaming events.
- **Recursion guard**: a ``contextvars.ContextVar`` prevents infinite loops
  when a ``SubscriberErrorEvent`` subscriber itself raises.

## Classes

- **`EventRegistry`** — Typed lifecycle event dispatcher.
