---
type: Wiki Summary
title: parrot.core.events.lifecycle.mixin
id: mod:parrot.core.events.lifecycle.mixin
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: EventEmitterMixin — uniform self.events interface for AbstractBot, AbstractClient,
  AbstractTool.
relates_to:
- concept: class:parrot.core.events.lifecycle.mixin.EventEmitterMixin
  rel: defines
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
- concept: mod:parrot.observability.bootstrap
  rel: references
---

# `parrot.core.events.lifecycle.mixin`

EventEmitterMixin — uniform self.events interface for AbstractBot, AbstractClient, AbstractTool.

FEAT-176 — Lifecycle Events System.

Mixin providing a per-instance ``EventRegistry`` accessible as ``self.events``.
The registry is lazily created on first access (fallback) or eagerly created when
``_init_events()`` is called from the host class ``__init__``.

By default, each instance's registry forwards events to the process-wide global
registry (see :mod:`parrot.core.events.lifecycle.global_registry`), enabling
cross-agent observability.  Opt out with ``forward_to_global=False``.

## Classes

- **`EventEmitterMixin`** — Mixin providing a uniform ``self.events: EventRegistry`` interface.
