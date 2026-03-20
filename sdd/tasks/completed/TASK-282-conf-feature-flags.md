# TASK-282: Add ENABLE_DATABASE_BOTS and ENABLE_REGISTRY_BOTS to parrot/conf.py

**Feature**: BotManager Initialization Flags Decoupling (FEAT-042)
**Spec**: `sdd/specs/decoupling-db-bots-botmanager.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: (none)
**Assigned-to**: claude-session

---

## Context

> Provides the two new module-level boolean constants required by subsequent
> tasks. Must be done first — all other FEAT-042 tasks depend on these constants.
> Implements spec Section 3 Module 1 and Section 4 "parrot/conf.py additions".

---

## Scope

Add two new boolean config variables to `parrot/conf.py` immediately after the
existing `ENABLE_CREWS` line, following the established `config.getboolean()`
pattern.

**NOT in scope**: Any changes to `parrot/manager/manager.py` or tests.

---

## Files to Modify

| File | Action |
|---|---|
| `parrot/conf.py` | MODIFY |

---

## Change Specification

Locate the line containing `ENABLE_CREWS = config.getboolean(...)` and insert
immediately after it:

```python
ENABLE_DATABASE_BOTS = config.getboolean("ENABLE_DATABASE_BOTS", fallback=False)
ENABLE_REGISTRY_BOTS = config.getboolean("ENABLE_REGISTRY_BOTS", fallback=True)
```

Both constants must be importable from `parrot.conf`.

---

## Acceptance Criteria

- [ ] `ENABLE_DATABASE_BOTS` exists in `parrot/conf.py` with `fallback=False`
- [ ] `ENABLE_REGISTRY_BOTS` exists in `parrot/conf.py` with `fallback=True`
- [ ] Both are importable: `from parrot.conf import ENABLE_DATABASE_BOTS, ENABLE_REGISTRY_BOTS`
- [ ] No ruff linting errors: `ruff check parrot/conf.py`

---

## Agent Instructions

1. Read `parrot/conf.py` to find the `ENABLE_CREWS` line
2. Insert the two new constants immediately after `ENABLE_CREWS`
3. Run `ruff check parrot/conf.py` and fix any issues
4. Verify imports work: `python -c "from parrot.conf import ENABLE_DATABASE_BOTS, ENABLE_REGISTRY_BOTS; print(ENABLE_DATABASE_BOTS, ENABLE_REGISTRY_BOTS)"`
5. Update status in `sdd/tasks/.index.json` → `"done"`
6. Move this file to `sdd/tasks/completed/TASK-282-conf-feature-flags.md`
7. Fill in the Completion Note below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-10
**Notes**: Added `ENABLE_DATABASE_BOTS = config.getboolean("ENABLE_DATABASE_BOTS", fallback=False)` and `ENABLE_REGISTRY_BOTS = config.getboolean("ENABLE_REGISTRY_BOTS", fallback=True)` immediately after the `ENABLE_CREWS` line in `parrot/conf.py`. Both import correctly with expected defaults. Three pre-existing ruff F401 warnings on line 7 (unused imports from `navigator.conf`) were present before this change and are out of scope.
