---
type: Wiki Overview
title: 'TASK-1671: Canonical identity mapper (cross-surface credential reuse)'
id: doc:sdd-tasks-completed-task-1671-canonical-identity-mapper-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 5 + resolved question (credentials reusable across surfaces).
  Normalizes
relates_to:
- concept: mod:parrot.auth.identity
  rel: mentions
---

# TASK-1671: Canonical identity mapper (cross-surface credential reuse)

**Feature**: FEAT-264 — Unified Credential Broker
**Spec**: `sdd/specs/unified-credential-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1667
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 + resolved question (credentials reusable across surfaces). Normalizes
the per-surface identities to one canonical vault key so a credential captured on A2A is
honored in chat and vice-versa.

---

## Scope

- Implement `CanonicalIdentityMapper` (`parrot/auth/identity.py`) that maps:
  - A2A: `message.metadata.from.email` / `from.id` (OID) / `sender` / `x-ms-user-email`.
  - MSAgentSDK: `activity.from_property.aad_object_id` (preferred) / channel `id`.
  to a single canonical key with precedence **OID → email**; fail closed (return `None`)
  for anonymous/dev with neither.
- Expose `to_canonical(raw_identity_or_claims) -> Optional[str]` used by the broker
  (`resolve` keys vault by canonical id; `channel` is audit context only).
- Unit tests: A2A email and MSAgentSDK `aad_object_id` for the same human map to the same
  key; anonymous → `None` (fail closed).

**NOT in scope**: the surfaces' extraction call sites (1672/1673 wire this in); the broker
itself (1667).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/identity.py` | CREATE | `CanonicalIdentityMapper` |
| `packages/ai-parrot/tests/unit/test_canonical_identity.py` | CREATE | mapping + fail-closed tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use (extraction precedents — DO NOT import, mirror)
```python
# parrot/a2a/server.py:289  A2AServer._extract_identity(message)
#   precedence: metadata.user_id → metadata.from.email → metadata.from.id → metadata.sender → metadata.x-ms-user-email
# integrations/msagentsdk/agent.py:108  ParrotM365Agent._extract_user_id(activity)
#   prefers from_property.aad_object_id (camelCase fallback aadObjectId) → from_property.id → "anonymous"
```

### Does NOT Exist
- ~~`CanonicalIdentityMapper`~~ / ~~`parrot.auth.identity`~~ — greenfield in this task.
- ~~a shared identity normalization today~~ — each surface extracts independently with different keys (this is the bug).

---

## Implementation Notes
- Prefer Entra OID when present (stable across surfaces); fall back to email; never fall
  back to a channel-scoped id for storage (that breaks reuse).
- Pure function / no I/O so the broker can call it cheaply per resolve.

## Acceptance Criteria
- [ ] A2A `from.email` and MSAgentSDK `aad_object_id` for the same user resolve to one key.
- [ ] Anonymous/dev (no OID/email) → `None` (caller fails closed).
- [ ] `pytest packages/ai-parrot/tests/unit/test_canonical_identity.py -v` passes; `ruff` clean.

## Agent Instructions
Standard SDD flow.

## Completion Note
*(Agent fills this in when done)*
