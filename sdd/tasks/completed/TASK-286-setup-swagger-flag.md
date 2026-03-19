# TASK-286: BotManager.setup — Use self.enable_swagger_api instead of global

**Feature**: BotManager Initialization Flags Decoupling (FEAT-042)
**Spec**: `sdd/specs/decoupling-db-bots-botmanager.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 1h)
**Depends-on**: TASK-283
**Assigned-to**: claude-session

---

## Context

> Replaces the global `ENABLE_SWAGGER` reference in `BotManager.setup()` with
> the instance attribute `self.enable_swagger_api` (added in TASK-283).
> This is the user-requested addition from spec line 51.

---

## Scope

Modify the `setup` method in `parrot/manager/manager.py` (currently around
line 683).

**NOT in scope**: Any other methods or files.

---

## Files to Modify

| File | Action |
|---|---|
| `parrot/manager/manager.py` | MODIFY |

---

## Change Specification

```python
# Before (line ~683):
if ENABLE_SWAGGER:
    setup_swagger(self.app)

# After:
if self.enable_swagger_api:
    setup_swagger(self.app)
```

After this change, `ENABLE_SWAGGER` may no longer be referenced anywhere in
`manager.py`. Verify and remove it from the `from ..conf import` statement if
it is truly unused (the import was restructured in TASK-283 to list all 5
constants alphabetically — remove `ENABLE_SWAGGER` if it is now only used for
the `enable_swagger_api` default, which is already set in `__init__`).

> Note: `ENABLE_SWAGGER` is still needed as the *default value* for the
> `enable_swagger_api` parameter in `__init__`. Keep it in the import list.

---

## Acceptance Criteria

- [ ] `setup()` uses `self.enable_swagger_api` (not global `ENABLE_SWAGGER`)
- [ ] `ENABLE_SWAGGER` still imported (used as default for `enable_swagger_api` in `__init__`)
- [ ] `ruff check parrot/manager/manager.py` passes

---

## Agent Instructions

1. Read `parrot/manager/manager.py` around lines 580–700 to find `setup()` and the `ENABLE_SWAGGER` usage
2. Replace `ENABLE_SWAGGER` → `self.enable_swagger_api` in `setup()`
3. Confirm `ENABLE_SWAGGER` is still in the import (for use in `__init__` default)
4. Run `ruff check parrot/manager/manager.py` and fix issues
5. Update `sdd/tasks/.index.json` → `"done"`
6. Move this file to `sdd/tasks/completed/TASK-286-setup-swagger-flag.md`
7. Fill in the Completion Note below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-10
**Notes**: Replaced `if ENABLE_SWAGGER:` with `if self.enable_swagger_api:` in `setup()` (previously line 729). `ENABLE_SWAGGER` remains in the import list as it is used as the default value for the `enable_swagger_api` parameter in `__init__`. No new ruff issues introduced.
