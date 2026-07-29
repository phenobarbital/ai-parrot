---
type: Wiki Summary
title: parrot.core.events.lifecycle
id: mod:parrot.core.events.lifecycle
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Lifecycle Events System — typed, frozen, observability-first events.
relates_to:
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
- concept: mod:parrot.core.events.lifecycle.events
  rel: references
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: references
- concept: mod:parrot.core.events.lifecycle.meta
  rel: references
- concept: mod:parrot.core.events.lifecycle.mixin
  rel: references
- concept: mod:parrot.core.events.lifecycle.provider
  rel: references
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
- concept: mod:parrot.core.events.lifecycle.subscribers.logging
  rel: references
- concept: mod:parrot.core.events.lifecycle.subscribers.opentelemetry
  rel: references
- concept: mod:parrot.core.events.lifecycle.subscribers.webhook
  rel: references
- concept: mod:parrot.core.events.lifecycle.trace
  rel: references
---

# `parrot.core.events.lifecycle`

Lifecycle Events System — typed, frozen, observability-first events.

FEAT-176. Public API curation (TASK-1197).

Usage::

    from parrot.core.events.lifecycle import (
        EventRegistry, EventEmitterMixin, TraceContext,
        BeforeInvokeEvent, AfterInvokeEvent,
        scope,
    )
