---
type: Wiki Overview
title: 'TASK-1538: Exports, demo agent, docs & integration tests'
id: doc:sdd-tasks-completed-task-1538-exports-demo-agent-and-docs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §3 Module 5. Surfaces the feature: export the public API from'
relates_to:
- concept: mod:parrot.auth
  rel: mentions
- concept: mod:parrot.auth.confirmation
  rel: mentions
- concept: mod:parrot.core.exceptions
  rel: mentions
---

# TASK-1538: Exports, demo agent, docs & integration tests

**Feature**: FEAT-235 — HITL Tool-Call Confirmation
**Spec**: `sdd/specs/hitl-confirmation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1535, TASK-1536, TASK-1537
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Surfaces the feature: export the public API from
`parrot/auth/__init__.py` (alongside the Grant exports), add a minimal demo agent
showing confirm-before-execute, write end-to-end integration tests, and document the
feature. This is the capstone task — it depends on the guard, the manager wiring, and
the declaration surface all being in place.

---

## Scope

- `parrot/auth/__init__.py`: export `ConfirmationGuard`, `ConfirmationConfig`,
  `ConfirmationDecision`, `ConfirmationWindowStore`, `InMemoryConfirmationWindowStore`
  next to the FEAT-211 grant exports (auth/__init__.py:51-58); add them to `__all__`.
- Demo agent under `agents/` (e.g. `agents/workday_checkin.py`) that registers a
  `workday_checkin` tool marked `requires_confirmation=True` with a `confirm_template`,
  wired to a `ConfirmationGuard` via `ToolManager.set_confirmation_guard()`. Model it
  on `agents/expense_approval.py`.
- End-to-end integration tests in
  `packages/ai-parrot/tests/test_confirmation_e2e.py` covering: BLOCK approve →
  execute; reject → cancelled ToolResult; grant→confirm ordering when both guards set.
- Docs: a short page under `docs/` describing how to mark a tool for confirmation,
  the `routing_meta` keys, BLOCK vs SUSPEND, edit-before-execute, and the
  confirmation window. Cross-reference the FEAT-211 grant docs.

**NOT in scope**: changing the guard/manager/declaration internals (TASK-1533–1537);
new HITL channels. Keep `agents/` changes additive (note: concrete files under
`agents/` may be gitignored — verify before assuming the demo is tracked).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/__init__.py` | MODIFY | export confirmation API + `__all__` |
| `agents/workday_checkin.py` | CREATE | demo agent (verify `agents/` tracking first) |
| `packages/ai-parrot/tests/test_confirmation_e2e.py` | CREATE | end-to-end integration tests |
| `docs/<…>/hitl-confirmation.md` | CREATE | user documentation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# what this task exposes (created by TASK-1533/1534):
from parrot.auth.confirmation import (
    ConfirmationGuard, ConfirmationConfig, ConfirmationDecision,
    ConfirmationWindowStore, InMemoryConfirmationWindowStore,
)
# manager wiring (created by TASK-1536):
# ToolManager.set_confirmation_guard(guard)
```

### Existing Signatures to Use
```python
# parrot/auth/__init__.py  (mirror the grant export block)
# Grants (bounded approval windows — FEAT-211)            # line 51
from .grants import (
    Grant, GrantConfig, GrantStore, InMemoryGrantStore, GrantGuard, GuardDecision,
)                                                          # lines 53-58
# ... "__all__" list includes "GrantGuard", "GuardDecision", etc.  # line 75+

# agents/expense_approval.py  (reference demo agent)
from parrot.core.exceptions import HumanInteractionInterrupt   # line 59
# QuickTeamsApprovalTool (BLOCK)                                # line 261
# EscalatingTeamsApprovalTool (SUSPEND)                         # line 302
# escalation policy + tool injection                           # lines 384-496
```

### Does NOT Exist
- ~~confirmation symbols in `parrot/auth/__init__.py`~~ — this task ADDS them.
- ~~a demo `workday_checkin` agent~~ — to be created.
- Note: per project memory, concrete agent files under `agents/` (e.g. `troc.py`)
  are **gitignored** — confirm whether `agents/workday_checkin.py` would be tracked;
  if not, place the demo where it will be committed (or document it as an example).

---

## Implementation Notes

### Key Constraints
- Exports must not break existing `from parrot.auth import GrantGuard` usage —
  additive only.
- The demo agent must run the full path: marked tool → `ConfirmationGuard.confirm()`
  → approval → execution.
- E2E tests should use a stub/fake `HumanInteractionManager` (no real channel I/O).

### References in Codebase
- `parrot/auth/__init__.py:51-75` — grant export block to mirror.
- `agents/expense_approval.py` — full agent + HITL wiring reference.

---

## Acceptance Criteria

- [ ] `from parrot.auth import ConfirmationGuard, ConfirmationConfig, ConfirmationDecision, ConfirmationWindowStore, InMemoryConfirmationWindowStore` works.
- [ ] The confirmation symbols appear in `parrot.auth.__all__`.
- [ ] Demo agent registers a `requires_confirmation` tool and confirms before executing.
- [ ] E2E: approve → real result; reject → `ToolResult(status="cancelled")`; grant→confirm order holds.
- [ ] Docs page exists and covers routing_meta keys, BLOCK/SUSPEND, edit, window.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_confirmation_e2e.py -v`
- [ ] Full feature suite green: `pytest packages/ai-parrot/tests/ -v -k confirmation`
- [ ] `ruff check packages/ai-parrot/src/parrot/auth/__init__.py`

---

## Test Specification
```python
# packages/ai-parrot/tests/test_confirmation_e2e.py
# - register a confirming tool on a ToolManager
# - set_confirmation_guard(ConfirmationGuard(InMemoryConfirmationWindowStore(), fake_manager))
# - approve path → tool result returned
# - reject path → ToolResult(success=False, status="cancelled")
# - both grant+confirm guards set → grant authorized first, then confirm asked
```

---

## Agent Instructions
1. Read spec §2/§3/§6 + the completed TASK-1533–1537. 2. Verify exports + `agents/` tracking.
3. Index → `in-progress`. 4. Implement + verify full suite. 5. Move to completed, index → `done`, note.

---

## Completion Note
**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: Exported ConfirmationGuard/Config/Decision/WindowStore/InMemoryWindowStore from
parrot.auth.__init__.py. Demo agent placed at packages/ai-parrot/examples/workday_checkin.py
(agents/ is gitignored so examples/ used instead; documented in task). 10 e2e tests pass.
Docs at docs/hitl-confirmation.md. Full suite: 79 tests pass.
**Deviations from spec**: Demo agent placed in packages/ai-parrot/examples/ instead of
agents/ because agents/ is gitignored (.gitignore:267:/agents/).

