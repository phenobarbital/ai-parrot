---
type: Wiki Summary
title: parrot.auth.resolver
id: mod:parrot.auth.resolver
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Permission resolvers for granular tool/toolkit access control.
relates_to:
- concept: class:parrot.auth.resolver.AbstractPermissionResolver
  rel: defines
- concept: class:parrot.auth.resolver.AllowAllResolver
  rel: defines
- concept: class:parrot.auth.resolver.DefaultPermissionResolver
  rel: defines
- concept: class:parrot.auth.resolver.DenyAllResolver
  rel: defines
- concept: class:parrot.auth.resolver.PBACPermissionResolver
  rel: defines
- concept: mod:parrot.auth.permission
  rel: references
---

# `parrot.auth.resolver`

Permission resolvers for granular tool/toolkit access control.

This module provides the resolver abstraction and default implementations:
- AbstractPermissionResolver: Pluggable ABC for permission checks
- DefaultPermissionResolver: RBAC implementation with hierarchy and LRU cache
- AllowAllResolver: Development/testing resolver (allows everything)
- DenyAllResolver: Lockdown resolver (denies restricted tools)
- PBACPermissionResolver: PBAC-backed Layer 2 safety net via PolicyEvaluator

The resolver is the single point of truth for "can this user execute this tool?"
It supports both Layer 1 (filtering) and Layer 2 (enforcement) permission checks.

## Classes

- **`AbstractPermissionResolver(ABC)`** — Pluggable resolver for tool permission checks.
- **`DefaultPermissionResolver(AbstractPermissionResolver)`** — Reference RBAC implementation with LRU-cached role expansion.
- **`AllowAllResolver(AbstractPermissionResolver)`** — Resolver that allows all tool executions.
- **`DenyAllResolver(AbstractPermissionResolver)`** — Resolver that denies all tool executions.
- **`PBACPermissionResolver(AbstractPermissionResolver)`** — PBAC-backed permission resolver — Layer 2 safety net.
