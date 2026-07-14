---
type: Wiki Summary
title: parrot.core.events.lifecycle.events
id: mod:parrot.core.events.lifecycle.events
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Re-exports for all concrete lifecycle event classes.
relates_to:
- concept: mod:parrot.core.events.lifecycle.events.agent
  rel: references
- concept: mod:parrot.core.events.lifecycle.events.client
  rel: references
- concept: mod:parrot.core.events.lifecycle.events.flow
  rel: references
- concept: mod:parrot.core.events.lifecycle.events.invoke
  rel: references
- concept: mod:parrot.core.events.lifecycle.events.message
  rel: references
- concept: mod:parrot.core.events.lifecycle.events.tool
  rel: references
---

# `parrot.core.events.lifecycle.events`

Re-exports for all concrete lifecycle event classes.

FEAT-176 — Lifecycle Events System.

Import any event class from this package for convenience:

    from parrot.core.events.lifecycle.events import BeforeInvokeEvent

SubscriberErrorEvent lives in meta.py (not here) because it is a
meta-level event emitted by the registry, not by domain code.
