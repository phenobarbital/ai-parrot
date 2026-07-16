---
type: Wiki Summary
title: parrot.auth.grants
id: mod:parrot.auth.grants
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Grant subsystem for bounded approval windows (FEAT-211).
relates_to:
- concept: class:parrot.auth.grants.Grant
  rel: defines
- concept: class:parrot.auth.grants.GrantConfig
  rel: defines
- concept: class:parrot.auth.grants.GrantGuard
  rel: defines
- concept: class:parrot.auth.grants.GrantStore
  rel: defines
- concept: class:parrot.auth.grants.GuardDecision
  rel: defines
- concept: class:parrot.auth.grants.InMemoryGrantStore
  rel: defines
- concept: mod:parrot.auth.permission
  rel: references
- concept: mod:parrot.human.manager
  rel: references
- concept: mod:parrot.human.models
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.auth.grants`

Grant subsystem for bounded approval windows (FEAT-211).

This module implements the tool-grant lifecycle:
  request → review → grant → observe → revoke

Key types:
  - Grant: Pydantic record for an approved action window.
  - GrantConfig: Configurable defaults (window duration, timeout, channel).
  - GrantStore: Abstract interface for grant persistence.
  - InMemoryGrantStore: Dict-backed store with TTL expiry and periodic cleanup.
  - GuardDecision: Result returned by GrantGuard.authorize().
  - GrantGuard: The Governor — decides allow / approve / deny for a tool call.

Design notes:
  - Grants are **in-memory only** and lost on restart. Persistence via the
    event ledger (FEAT-212) is a planned future enhancement.
  - Tools called directly via AbstractTool.execute() without going through
    ToolManager are NOT gated. The agent loop always uses ToolManager.
  - The guard is **fail-closed**: requires_grant + no active grant + no HITL
    channel → deny immediately.

## Classes

- **`Grant(BaseModel)`** — A bounded-window approval record.
- **`GrantConfig(BaseModel)`** — Configurable defaults for the grant subsystem.
- **`GrantStore(ABC)`** — Abstract interface for grant persistence.
- **`InMemoryGrantStore(GrantStore)`** — Dict-backed grant store with TTL expiry and periodic cleanup.
- **`GuardDecision(BaseModel)`** — Result of GrantGuard.authorize().
- **`GrantGuard`** — The Governor: decides allow / approve / deny for a tool call.
