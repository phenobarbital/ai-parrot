---
type: Wiki Overview
title: 'TASK-1185: Add trace_context field to PermissionContext'
id: doc:sdd-tasks-completed-task-1185-permission-context-trace-field-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Module 15 of the spec. `PermissionContext` is the carrier passed through
  the toolkit wrapper (`_permission_context` kwarg) and stored on tool instances as
  `self._current_pctx`. For lifecycle events to propagate trace identity across agent
  → tool and agent → sub-agent boundaries, '
relates_to:
- concept: mod:parrot.auth.permission
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1185: Add trace_context field to PermissionContext

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-1182
**Assigned-to**: unassigned

---

## Context

Module 15 of the spec. `PermissionContext` is the carrier passed through the toolkit wrapper (`_permission_context` kwarg) and stored on tool instances as `self._current_pctx`. For lifecycle events to propagate trace identity across agent → tool and agent → sub-agent boundaries, `PermissionContext` must carry an optional `trace_context` field. This task is the only place that field is added.

Spec section: §3 Module 15 (path resolved: `packages/ai-parrot/src/parrot/auth/permission.py:79`).

This task is **parallel-safe** with TASK-1183 / TASK-1184 — it only touches `auth/permission.py` and depends only on TASK-1182 (`TraceContext`).

---

## Scope

- Add `trace_context: Optional[TraceContext] = None` to the `PermissionContext` dataclass.
- Place the new field BETWEEN `channel` and `extra` so existing positional construction (extremely rare in this codebase, all call sites use kwargs) is unaffected. Default `None` makes it non-breaking.
- Import `TraceContext` from `parrot.core.events.lifecycle.trace`.
- Add a unit test verifying the new field defaults to `None` and that existing construction (no `trace_context=` kwarg) continues to work.
- Run the existing `parrot/auth/` test suite to confirm zero regressions.

**NOT in scope**: emitting events, populating the field at call sites (TASK-1195 propagates from agent to tool; TASK-1193 attaches to the bot's context).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/permission.py` | MODIFY | Add `trace_context: Optional[TraceContext] = None` field. |
| `packages/ai-parrot/tests/unit/auth/test_permission_context_trace.py` | CREATE | Test field default + roundtrip. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Optional
from parrot.core.events.lifecycle.trace import TraceContext   # from TASK-1182
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/permission.py:79 — VERIFIED
from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class PermissionContext:
    session: UserSession
    request_id: Optional[str] = None
    channel: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)
```

**After this task:**

```python
@dataclass
class PermissionContext:
    session: UserSession
    request_id: Optional[str] = None
    channel: Optional[str] = None
    trace_context: Optional[TraceContext] = None      # ← NEW
    extra: dict[str, Any] = field(default_factory=dict)
```

### Does NOT Exist

- ~~`PermissionContext.trace_id`~~ — there is no flat `trace_id` field; the whole `TraceContext` lives here.
- ~~`PermissionContext.span_id`~~ — same.
- ~~`PermissionContext` as a Pydantic model~~ — it is a plain `@dataclass`.

---

## Implementation Notes

### Why this is non-breaking

`grep -r "PermissionContext(" packages/ai-parrot/src/` shows every construction uses keyword arguments (`PermissionContext(session=...)`). Default `None` means existing callers don't break. The implementer should confirm this with a quick grep before merging.

### Where the field is populated later

- **TASK-1193** (`AbstractBot`): when emitting `BeforeInvokeEvent`, the bot creates a root `TraceContext` (or uses the one the caller passed via `ask(..., trace_context=ctx)`) and attaches it to the request's `PermissionContext` so tools see it.
- **TASK-1195** (`AbstractTool`): when receiving a tool call, `self._current_pctx.trace_context` is read; `child()` is called to mint a sub-span for the tool's emitted events.

### Key Constraints

- Do NOT change the field order of `session`, `request_id`, `channel`, `extra`.
- Do NOT add validation logic — defaulted optional field is enough.
- Add an Optional import only if not already present (verify the existing file's imports first).

---

## Acceptance Criteria

- [ ] `PermissionContext` now has a `trace_context: Optional[TraceContext] = None` field.
- [ ] `PermissionContext(session=...)` (no trace_context kwarg) still works and yields `.trace_context is None`.
- [ ] `PermissionContext(session=..., trace_context=ctx).trace_context is ctx`.
- [ ] Existing `parrot/auth/` test suite passes: `pytest packages/ai-parrot/tests/unit/auth/ -v`.
- [ ] Full integration suite passes without regressions: `pytest packages/ai-parrot/tests/ -v -k "permission or auth"`.
- [ ] `ruff check packages/ai-parrot/src/parrot/auth/permission.py` is clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_permission_context_trace.py
import pytest

from parrot.auth.permission import PermissionContext
from parrot.core.events.lifecycle.trace import TraceContext


# NOTE: UserSession construction may need a fixture; if so, copy the existing
# pattern from packages/ai-parrot/tests/unit/auth/ or use a Mock.
@pytest.fixture
def user_session():
    from unittest.mock import MagicMock
    return MagicMock(name="UserSession")


class TestPermissionContextTrace:
    def test_default_is_none(self, user_session):
        pctx = PermissionContext(session=user_session)
        assert pctx.trace_context is None

    def test_accepts_trace_context(self, user_session):
        ctx = TraceContext.new_root()
        pctx = PermissionContext(session=user_session, trace_context=ctx)
        assert pctx.trace_context is ctx

    def test_existing_fields_unchanged(self, user_session):
        pctx = PermissionContext(
            session=user_session, request_id="req-1", channel="cli",
        )
        assert pctx.request_id == "req-1"
        assert pctx.channel == "cli"
        assert pctx.extra == {}
```

---

## Agent Instructions

1. Read the spec section §3 Module 15 and the Codebase Contract above.
2. Confirm TASK-1182 is in `sdd/tasks/completed/` (`TraceContext` must exist).
3. `grep -rn "PermissionContext(" packages/ai-parrot/src/` — verify all call sites use kwargs (sanity check).
4. Apply the field addition, run the auth test suite, run a broader smoke test to confirm no regressions.
5. Update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-15
**Notes**: Added `trace_context: Optional[TraceContext] = None` between `channel` and `extra` using TYPE_CHECKING import to avoid circular dependency risk. All 7 new tests pass; existing channel tests and auth test suite pass (6 pre-existing failures in test_dataset_guard.py and test_pbac_setup.py unrelated to this change). Ruff clean.

**Deviations from spec**: Test placed at `tests/unit/auth/test_permission_context_trace.py` as specified. Used real `UserSession` fixture (not MagicMock) to match existing test_permission_context_channel.py pattern. TYPE_CHECKING guard used for TraceContext import to avoid any circular import risk at runtime.
