---
type: Wiki Summary
title: parrot.autonomous.evb
id: mod:parrot.autonomous.evb
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Backward-compatible re-export of EventBus from the canonical location.
relates_to:
- concept: mod:parrot.core.events.evb
  rel: references
---

# `parrot.autonomous.evb`

Backward-compatible re-export of EventBus from the canonical location.

The EventBus implementation now lives in ``parrot.core.events``.
This module is kept for backward compatibility with existing code that
imports from ``parrot.autonomous.evb``.
