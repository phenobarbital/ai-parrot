---
type: Wiki Summary
title: parrot.integrations.matrix.hook
id: mod:parrot.integrations.matrix.hook
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Matrix protocol hook for AutonomousOrchestrator.
relates_to:
- concept: class:parrot.integrations.matrix.hook.MatrixHook
  rel: defines
- concept: mod:parrot.core.hooks.base
  rel: references
- concept: mod:parrot.core.hooks.models
  rel: references
- concept: mod:parrot.integrations.matrix.client
  rel: references
---

# `parrot.integrations.matrix.hook`

Matrix protocol hook for AutonomousOrchestrator.

Concrete implementation of :class:`~parrot.core.hooks.base.BaseHook`
for the Matrix messaging protocol. Listens to Matrix room messages via
mautrix-python and routes them to agents/crews.

This module auto-registers ``MatrixHook`` with
:class:`~parrot.core.hooks.base.HookRegistry` on import::

    import parrot.integrations.matrix.hook   # triggers auto-registration

Features:
- Listens to room messages via /sync loop
- Filters by allowed_users (MXIDs)
- Supports command_prefix (e.g., "!ask")
- Routes to specific agents based on room_routing config
- Auto-reply support via Matrix

## Classes

- **`MatrixHook(BaseHook)`** — Matrix message listener via mautrix-python.
