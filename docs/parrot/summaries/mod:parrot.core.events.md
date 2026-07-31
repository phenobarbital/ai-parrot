---
type: Wiki Summary
title: parrot.core.events
id: mod:parrot.core.events
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Event bus infrastructure for AI-Parrot.
relates_to:
- concept: mod:parrot.core
  rel: references
---

# `parrot.core.events`

Event bus infrastructure for AI-Parrot.

Provides Redis-backed pub/sub with glob-pattern matching and event history.
This is the canonical location — imported by both ``parrot.autonomous`` and
``parrot.integrations``.

Public API::

    from parrot.core.events import EventBus, Event, EventPriority, EventSubscription
