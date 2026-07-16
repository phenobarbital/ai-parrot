---
type: Wiki Overview
title: 'TASK-1533: Confirmation models & window store'
id: doc:sdd-tasks-completed-task-1533-confirmation-models-and-window-store-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation of the confirmation subsystem (spec §2 Data Models, §3 Module
  1).
relates_to:
- concept: mod:parrot.auth.confirmation
  rel: mentions
---

# TASK-1533: Confirmation models & window store

**Feature**: FEAT-235 — HITL Tool-Call Confirmation
**Spec**: `sdd/specs/hitl-confirmation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation of the confirmation subsystem (spec §2 Data Models, §3 Module 1).
Every other task depends on these models and the window store. They mirror the
FEAT-211 grant subsystem (`parrot/auth/grants.py`) structurally so the two guards
stay symmetric.

---

## Scope

- Create `parrot/auth/confirmation.py` with:
  - `ConfirmationConfig(BaseModel)` — `window_seconds: int = Field(0, ge=0)`
    (0 = always re-ask), `approval_timeout: float = Field(120.0, gt=0)`,
    `default_channel: str = "telegram"`, `max_edit_retries: int = Field(1, ge=0)`.
  - `ConfirmationDecision(BaseModel)` — `allowed: bool`,
    `status: str = "confirmed"` (one of `confirmed | cancelled | timeout |
    not_required`), `reason: str`, `parameters: Optional[Dict[str, Any]] = None`.
  - `ConfirmationWindowStore(ABC)` — abstract methods
    `async def is_confirmed(self, owner_id, tool_name, args_hash) -> bool` and
    `async def record(self, owner_id, tool_name, args_hash, *, window_seconds) -> None`.
  - `InMemoryConfirmationWindowStore(ConfirmationWindowStore)` — `asyncio.Lock`-guarded
    dict keyed by `(owner_id, tool_name, args_hash)` storing an expiry timestamp;
    `is_confirmed` returns True only if a non-expired entry exists.
  - A module-level helper `compute_args_hash(parameters: dict) -> str` producing a
    stable hash over normalized params (sorted keys, deterministic serialization).
- Write unit tests in `packages/ai-parrot/tests/test_confirmation_models.py`.

**NOT in scope**: `ConfirmationGuard.confirm()` (TASK-1534), briefing/edit
(TASK-1535), ToolManager wiring (TASK-1536), `@tool`/spawn changes (TASK-1537),
`__init__.py` exports (TASK-1538). Do NOT add a Redis store backend yet.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/confirmation.py` | CREATE | Models + window store + args-hash helper |
| `packages/ai-parrot/tests/test_confirmation_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
import asyncio
```

### Existing Signatures to Use (structural template — DO NOT import, mirror)
```python
# packages/ai-parrot/src/parrot/auth/grants.py
class GrantConfig(BaseModel):                       # line 95
    window_seconds: int = Field(900, gt=0)          # line 107
    approval_timeout: float = Field(120.0, gt=0)    # line 108
    default_channel: str = "telegram"               # line 109
class GrantStore(ABC):                              # line 114
    @abstractmethod
    async def grant(self, owner_id, scope, *, granted_by, window_seconds) -> "Grant": ...   # 123
    @abstractmethod
    async def is_allowed(self, owner_id: str, scope: str) -> bool: ...                       # 145
class InMemoryGrantStore(GrantStore):               # line 185 (asyncio.Lock pattern to copy)
class GuardDecision(BaseModel):                     # line 320
    allowed: bool                                   # line 330
    reason: str                                     # line 331
```

### Does NOT Exist
- ~~`parrot.auth.confirmation`~~ — this task CREATES it.
- ~~`RedisConfirmationWindowStore`~~ — not in scope; only the in-memory store.
- ~~`GrantConfig.max_edit_retries`~~ — that field is NEW to `ConfirmationConfig`,
  not present on `GrantConfig`.

---

## Implementation Notes

### Pattern to Follow
Copy the shape of `GrantConfig` / `GuardDecision` / `GrantStore` /
`InMemoryGrantStore` from `parrot/auth/grants.py`. Use the same `asyncio.Lock`
concurrency approach `InMemoryGrantStore` uses (grants.py:185-299).

### Key Constraints
- Async throughout for the store; Pydantic for all models.
- `window_seconds=0` (default) MUST mean "no window" — `record()` with
  `window_seconds=0` should store nothing (so `is_confirmed` always returns False).
- `compute_args_hash` must be deterministic across runs (e.g. `hashlib.sha256` over
  `json.dumps(parameters, sort_keys=True, default=str)`).
- `self.logger = logging.getLogger(__name__)` on the store.

### References in Codebase
- `parrot/auth/grants.py:95-332` — the exact structural template.

---

## Acceptance Criteria

- [ ] `from parrot.auth.confirmation import (ConfirmationConfig, ConfirmationDecision, ConfirmationWindowStore, InMemoryConfirmationWindowStore, compute_args_hash)` works.
- [ ] `ConfirmationConfig` defaults: `window_seconds=0`, `approval_timeout=120.0`, `default_channel="telegram"`, `max_edit_retries=1`.
- [ ] `InMemoryConfirmationWindowStore.is_confirmed` returns False for unknown keys, True within window, False after expiry, False when `window_seconds=0` was recorded.
- [ ] `compute_args_hash` is stable for equal dicts regardless of key order and differs for different values.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_confirmation_models.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/auth/confirmation.py`

---

## Test Specification
```python
# packages/ai-parrot/tests/test_confirmation_models.py
import pytest
from parrot.auth.confirmation import (
    ConfirmationConfig, ConfirmationDecision,
    InMemoryConfirmationWindowStore, compute_args_hash,
)


def test_config_defaults():
    c = ConfirmationConfig()
    assert c.window_seconds == 0 and c.max_edit_retries == 1


def test_args_hash_order_independent():
    assert compute_args_hash({"a": 1, "b": 2}) == compute_args_hash({"b": 2, "a": 1})
    assert compute_args_hash({"a": 1}) != compute_args_hash({"a": 2})


async def test_window_zero_never_confirms():
    store = InMemoryConfirmationWindowStore()
    await store.record("u1", "t", "h", window_seconds=0)
    assert await store.is_confirmed("u1", "t", "h") is False


async def test_window_records_and_expires():
    store = InMemoryConfirmationWindowStore()
    await store.record("u1", "t", "h", window_seconds=300)
    assert await store.is_confirmed("u1", "t", "h") is True
    assert await store.is_confirmed("u1", "t", "other") is False
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/hitl-confirmation.spec.md` (§2, §3, §6).
2. Verify the Codebase Contract against `parrot/auth/grants.py`.
3. Update the index entry to `in-progress`.
4. Implement, verify acceptance criteria.
5. Move this file to `sdd/tasks/completed/`, update index to `done`, fill the note.

---

## Completion Note

**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: Created `parrot/auth/confirmation.py` with all models, ABC store,
in-memory implementation (asyncio.Lock-guarded dict + TTL expiry), and
compute_args_hash helper. All 21 tests pass. ruff clean.
**Deviations from spec**: none
