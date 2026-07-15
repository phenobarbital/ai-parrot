---
type: Wiki Summary
title: parrot.core.events.lifecycle.provider
id: mod:parrot.core.events.lifecycle.provider
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: EventProvider Protocol for batch subscriber registration.
relates_to:
- concept: class:parrot.core.events.lifecycle.provider.EventProvider
  rel: defines
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
---

# `parrot.core.events.lifecycle.provider`

EventProvider Protocol for batch subscriber registration.

FEAT-176 — Lifecycle Events System.

Any object that implements ``register(self, registry: EventRegistry) -> None``
conforms to this protocol.  No inheritance required — conformance is
structural (duck-typed) via ``typing.Protocol`` with ``@runtime_checkable``
so ``isinstance()`` works at runtime.

## Classes

- **`EventProvider(Protocol)`** — Bundles multiple subscriber callbacks for batch registration.
