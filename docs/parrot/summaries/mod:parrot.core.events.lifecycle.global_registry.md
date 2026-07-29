---
type: Wiki Summary
title: parrot.core.events.lifecycle.global_registry
id: mod:parrot.core.events.lifecycle.global_registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Global registry singleton and scope() context manager.
relates_to:
- concept: func:parrot.core.events.lifecycle.global_registry.get_global_registry
  rel: defines
- concept: func:parrot.core.events.lifecycle.global_registry.scope
  rel: defines
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
---

# `parrot.core.events.lifecycle.global_registry`

Global registry singleton and scope() context manager.

FEAT-176 — Lifecycle Events System.

This module provides the process-wide singleton ``EventRegistry`` that
observes every lifecycle event unless an agent opts out via
``forward_to_global=False``.

The ``scope()`` context manager replaces the global registry with a fresh
one for the duration of the block, then restores the previous registry on
exit — even if the block raises. This is required for test isolation,
especially under pytest parallelism.

Storage uses a ``ContextVar`` so that each asyncio task sees a coherent
registry and nested ``scope()`` blocks operate independently via the
ContextVar token/reset pattern.

## Functions

- `def get_global_registry() -> EventRegistry` — Return the process-wide singleton ``EventRegistry``.
- `def scope() -> Iterator[EventRegistry]` — Replace the global registry with a fresh one for the block duration.
