---
type: Wiki Overview
title: 'TASK-1403: Grant Models & InMemoryGrantStore'
id: doc:sdd-tasks-completed-task-1403-grant-models-and-store-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundational task for the grant subsystem. It creates the Pydantic
relates_to:
- concept: mod:parrot.auth.grants
  rel: mentions
---

# TASK-1403: Grant Models & InMemoryGrantStore

**Feature**: FEAT-211 — Tool Grants & Bounded Approval Windows
**Spec**: `sdd/specs/FEAT-211-tool-grants-bounded-approval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec Module 1: Grant models + store.

This is the foundational task for the grant subsystem. It creates the Pydantic
data models (`Grant`, `GrantConfig`), the abstract `GrantStore` interface, and
the `InMemoryGrantStore` implementation with TTL-based expiry and periodic
cleanup. All subsequent tasks depend on these types.

The bounded-approval-window concept is central: a `Grant` records who approved
what, when, and for how long. `InMemoryGrantStore` enforces expiry at query
time and runs periodic cleanup to prevent unbounded memory growth.

---

## Scope

- Create `packages/ai-parrot/src/parrot/auth/grants.py` with:
  - `Grant(BaseModel)` — grant record with `grant_id`, `owner_id`, `scope`,
    `granted_by`, `created_at`, `expires_at`, `revoked`; methods `is_active(now)`
    and `covers(scope)`.
  - `GrantConfig(BaseModel)` — configurable defaults: `window_seconds` (default 900),
    `approval_timeout` (default 120.0), `default_channel` (default `"telegram"`).
  - `GrantStore(ABC)` — abstract interface with `grant()`, `is_allowed()`,
    `revoke()`, `list_active()`.
  - `InMemoryGrantStore(GrantStore)` — dict-backed store with asyncio.Lock for
    concurrency safety and periodic cleanup of expired grants.
- Write unit tests in `packages/ai-parrot/tests/tools/test_grants.py`.

**NOT in scope**:
- `GrantGuard` / `GuardDecision` (TASK-1404)
- ToolManager integration (TASK-1405)
- Auth exports wiring (TASK-1406)
- Redis or persistent backend (future FEAT-212)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/grants.py` | CREATE | Grant, GrantConfig, GrantStore ABC, InMemoryGrantStore |
| `packages/ai-parrot/tests/tools/test_grants.py` | CREATE | Unit tests for models + store |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from pydantic import BaseModel, Field       # standard pydantic (already used everywhere)
from abc import ABC, abstractmethod         # standard library
from uuid import uuid4                      # standard library
from datetime import datetime               # standard library
import asyncio                              # for asyncio.Lock in InMemoryGrantStore
import logging                              # for self.logger pattern
```

### Existing Signatures to Use
```python
# No existing classes to extend — Grant/GrantStore are new.
# Pattern reference only:

# packages/ai-parrot/src/parrot/tools/manager.py:285
# Injection pattern to mirror for future set_grant_guard():
def set_resolver(self, resolver: "AbstractPermissionResolver") -> None:
    self._resolver = resolver
```

### Does NOT Exist
- ~~`parrot.auth.grants`~~ — **does not exist yet**. This task creates it.
- ~~`Grant`, `GrantStore`, `GrantGuard`~~ — none of these exist anywhere in the codebase.
- ~~`BusinessHours`~~ — exists in `human/models.py` but is for escalation scheduling, NOT grants.
- ~~`automation_window`, `bounded_grant`~~ — no such concept exists anywhere.

---

## Implementation Notes

### Pattern to Follow
```python
# Pydantic model pattern (standard throughout codebase)
class Grant(BaseModel):
    grant_id: str = Field(default_factory=lambda: str(uuid4()))
    owner_id: str
    scope: str
    granted_by: str
    created_at: datetime
    expires_at: datetime
    revoked: bool = False

    def is_active(self, now: datetime | None = None) -> bool:
        if now is None:
            now = datetime.now(timezone.utc)
        return (not self.revoked) and now < self.expires_at

    def covers(self, scope: str) -> bool:
        return self.scope == scope or self.scope == "tool:*"
```

### Key Constraints
- `Grant.is_active()` must check BOTH `revoked` and `expires_at`.
- `Grant.covers()` must support wildcard scope `"tool:*"`.
- `InMemoryGrantStore` must use `asyncio.Lock` to prevent TOCTOU races.
- `InMemoryGrantStore._cleanup()` should remove expired/revoked grants from
  the internal dict (periodic or on-demand).
- Window is **fixed** from approval time (not sliding). The `expires_at` is
  set once at grant creation: `created_at + timedelta(seconds=window_seconds)`.
- Use `self.logger = logging.getLogger(__name__)` in store classes.
- All store methods are `async`.

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/permission.py` — `UserSession`/`PermissionContext` pattern (dataclass + Pydantic).
- `packages/ai-parrot/src/parrot/tools/manager.py:285` — `set_resolver` injection pattern to mirror later.

---

## Acceptance Criteria

- [ ] `Grant.is_active()` returns True within window, False after expiry, False when revoked.
- [ ] `Grant.covers()` returns True for exact scope match and wildcard `"tool:*"`.
- [ ] `InMemoryGrantStore.grant()` creates a Grant with correct `expires_at`.
- [ ] `InMemoryGrantStore.is_allowed()` returns True for active grants covering scope.
- [ ] `InMemoryGrantStore.revoke()` immediately invalidates a grant.
- [ ] `InMemoryGrantStore.list_active()` returns only non-expired, non-revoked grants.
- [ ] Concurrent access is safe (asyncio.Lock).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_grants.py -v -k "grant_is_active or grant_covers or inmemory"`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/auth/grants.py`.
- [ ] Import works: `from parrot.auth.grants import Grant, GrantConfig, GrantStore, InMemoryGrantStore`.

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_grants.py
import pytest
from datetime import datetime, timedelta, timezone
from parrot.auth.grants import Grant, GrantConfig, GrantStore, InMemoryGrantStore


class TestGrant:
    def test_grant_is_active_within_window(self):
        """Grant is active before expires_at and not revoked."""
        now = datetime.now(timezone.utc)
        g = Grant(
            owner_id="user-1", scope="tool:deploy", granted_by="admin",
            created_at=now, expires_at=now + timedelta(minutes=15),
        )
        assert g.is_active(now + timedelta(minutes=5)) is True

    def test_grant_is_active_expired(self):
        """Grant is inactive after expires_at."""
        now = datetime.now(timezone.utc)
        g = Grant(
            owner_id="user-1", scope="tool:deploy", granted_by="admin",
            created_at=now, expires_at=now + timedelta(minutes=15),
        )
        assert g.is_active(now + timedelta(minutes=20)) is False

    def test_grant_is_active_revoked(self):
        """Revoked grant is inactive even within window."""
        now = datetime.now(timezone.utc)
        g = Grant(
            owner_id="user-1", scope="tool:deploy", granted_by="admin",
            created_at=now, expires_at=now + timedelta(minutes=15),
            revoked=True,
        )
        assert g.is_active(now + timedelta(minutes=5)) is False

    def test_grant_covers_exact_scope(self):
        """Grant covers its exact scope."""
        g = Grant(
            owner_id="u", scope="tool:deploy", granted_by="a",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        assert g.covers("tool:deploy") is True
        assert g.covers("tool:delete") is False

    def test_grant_covers_wildcard(self):
        """Wildcard scope covers any tool scope."""
        g = Grant(
            owner_id="u", scope="tool:*", granted_by="a",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        assert g.covers("tool:deploy") is True
        assert g.covers("tool:anything") is True


@pytest.mark.asyncio
class TestInMemoryGrantStore:
    async def test_grant_and_is_allowed(self):
        """grant() creates entry; is_allowed() returns True within window."""
        store = InMemoryGrantStore()
        grant = await store.grant("user-1", "tool:deploy",
                                  granted_by="admin", window_seconds=900)
        assert grant.owner_id == "user-1"
        assert await store.is_allowed("user-1", "tool:deploy") is True

    async def test_is_allowed_false_after_expiry(self):
        """is_allowed() returns False after grant expires."""
        store = InMemoryGrantStore()
        await store.grant("user-1", "tool:deploy",
                          granted_by="admin", window_seconds=0)
        # window_seconds=0 means expires_at == created_at → immediately expired
        assert await store.is_allowed("user-1", "tool:deploy") is False

    async def test_revoke_invalidates_grant(self):
        """revoke() marks grant as revoked; is_allowed() returns False."""
        store = InMemoryGrantStore()
        grant = await store.grant("user-1", "tool:deploy",
                                  granted_by="admin", window_seconds=900)
        assert await store.revoke(grant.grant_id) is True
        assert await store.is_allowed("user-1", "tool:deploy") is False

    async def test_list_active_filters_expired_and_revoked(self):
        """list_active() only returns non-expired, non-revoked grants."""
        store = InMemoryGrantStore()
        g1 = await store.grant("user-1", "tool:a", granted_by="admin", window_seconds=900)
        await store.grant("user-1", "tool:b", granted_by="admin", window_seconds=0)
        active = await store.list_active("user-1")
        assert len(active) == 1
        assert active[0].grant_id == g1.grant_id
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-211-tool-grants-bounded-approval.spec.md` for full context
2. **Check dependencies** — this task has no dependencies (first in chain)
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `parrot/auth/grants.py` does NOT exist yet (`ls` / `grep`)
   - Confirm no `Grant` class exists anywhere in `parrot/auth/`
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/tool-grants-bounded-approval.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1403-grant-models-and-store.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-01
**Notes**: Created `packages/ai-parrot/src/parrot/auth/grants.py` with `Grant`,
`GrantConfig`, `GrantStore` (ABC), and `InMemoryGrantStore` with asyncio.Lock,
TTL expiry, and `cleanup()`. Test file created at
`packages/ai-parrot/tests/tools/test_grants.py`. All 17 model/store tests pass,
ruff reports no issues.

**Deviations from spec**: None.
