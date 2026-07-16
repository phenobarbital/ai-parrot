---
type: Wiki Summary
title: parrot.core.events.lifecycle.base
id: mod:parrot.core.events.lifecycle.base
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base class for all lifecycle events.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: defines
- concept: mod:parrot.core.events.lifecycle.trace
  rel: references
---

# `parrot.core.events.lifecycle.base`

Abstract base class for all lifecycle events.

FEAT-176 — Lifecycle Events System.

Every concrete lifecycle event must inherit from LifecycleEvent and be
decorated with ``@dataclass(frozen=True)``. Frozen dataclasses are ~5x
faster to instantiate than Pydantic models (spec §7 Pattern constraints)
and provide immutability guarantees at the Python level.

## Classes

- **`LifecycleEvent(ABC)`** — Read-only base class for every lifecycle event.
