---
type: Wiki Summary
title: parrot.auth.permission
id: mod:parrot.auth.permission
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Permission data models for granular tool/toolkit access control.
relates_to:
- concept: class:parrot.auth.permission.PermissionContext
  rel: defines
- concept: class:parrot.auth.permission.UserSession
  rel: defines
- concept: func:parrot.auth.permission.to_eval_context
  rel: defines
- concept: mod:parrot.core.events.lifecycle.trace
  rel: references
---

# `parrot.auth.permission`

Permission data models for granular tool/toolkit access control.

This module provides foundational data structures for the permission system:
- UserSession: Immutable session carrying user identity and role claims
- PermissionContext: Request-scoped wrapper with session and metadata
- to_eval_context: Bridge function from PermissionContext to EvalContext

These are lightweight structures that flow through the execution chain,
enabling Layer 1 (filtering) and Layer 2 (enforcement) permission checks.

## Classes

- **`UserSession`** — Minimal session carrying identity and role claims.
- **`PermissionContext`** — Request-scoped wrapper grouping session with extra context.

## Functions

- `def to_eval_context(context: 'PermissionContext') -> 'EvalContext'` — Bridge a PermissionContext to a navigator-auth EvalContext.
