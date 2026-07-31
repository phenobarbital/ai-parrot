---
type: Wiki Summary
title: parrot.core.events.lifecycle.legacy_bridge
id: mod:parrot.core.events.lifecycle.legacy_bridge
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: _LegacyEventBridge — routes new typed events back to legacy _listeners callbacks.
relates_to:
- concept: mod:parrot.core.events.lifecycle.events
  rel: references
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
---

# `parrot.core.events.lifecycle.legacy_bridge`

_LegacyEventBridge — routes new typed events back to legacy _listeners callbacks.

FEAT-176 — Lifecycle Events System.

AbstractBot's legacy API (``add_event_listener`` / ``_trigger_event``) is preserved
by registering a ``_LegacyEventBridge`` subscriber during ``__init__``.  When
an ``AgentStatusChangedEvent`` is dispatched on the bot's ``EventRegistry``, the
bridge invokes every callback stored in ``self._listeners[EVENT_STATUS_CHANGED]``.

This ensures that code written against the legacy string-keyed event system
continues to work unchanged, while new code can subscribe to typed events directly.
