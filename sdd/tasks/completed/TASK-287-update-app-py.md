# TASK-287: Update app.py to pass enable_database_bots=True

**Feature**: BotManager Initialization Flags Decoupling (FEAT-042)
**Spec**: `sdd/specs/decoupling-db-bots-botmanager.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: TASK-283
**Assigned-to**: claude-session

---

## Context

> The project's `app.py` currently instantiates `BotManager()` with no
> arguments. After TASK-283, `enable_database_bots` defaults to `False`.
> Since this project uses database bots, `app.py` must explicitly opt in.
> Per spec Section 5 Migration and user's open question answer (lines 412–413).

---

## Scope

Modify `app.py` (project root) to pass `enable_database_bots=True` when
instantiating `BotManager`.

**NOT in scope**: Any changes to `parrot/manager/manager.py` or tests.

---

## Files to Modify

| File | Action |
|---|---|
| `app.py` | MODIFY |

---

## Change Specification

```python
# Before:
self.bot_manager = BotManager()

# After:
self.bot_manager = BotManager(enable_database_bots=True)
```

---

## Acceptance Criteria

- [ ] `BotManager(enable_database_bots=True)` is used in `app.py`
- [ ] No other arguments changed (backwards-compatible)
- [ ] `ruff check app.py` passes (if applicable)

---

## Agent Instructions

1. Read `app.py` to find the `BotManager()` instantiation (currently line 74)
2. Add `enable_database_bots=True` argument
3. Update `sdd/tasks/.index.json` → `"done"`
4. Move this file to `sdd/tasks/completed/TASK-287-update-app-py.md`
5. Fill in the Completion Note below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-10
**Notes**: Added `enable_database_bots=True` to `BotManager()` instantiation at `app.py:74`.
Pre-existing F841 ruff warning (unused `tasker` variable at line 62) was not introduced by this change and is out of scope.
