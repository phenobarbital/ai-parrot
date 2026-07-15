---
type: Wiki Summary
title: parrot.core
id: mod:parrot.core
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Shared infrastructure for AI-Parrot.
---

# `parrot.core`

Shared infrastructure for AI-Parrot.

This package contains cross-cutting infrastructure reused by multiple
subsystems (``parrot.autonomous``, ``parrot.integrations``, etc.):

- ``parrot.core.hooks``  — Hook system (BaseHook, HookManager, HookEvent)
- ``parrot.core.events`` — EventBus (Redis-backed pub/sub)
