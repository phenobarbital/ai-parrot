# TASK-285: BotManager.on_startup — Replace global ENABLE_CREWS and skip BotConfigStorage

**Feature**: BotManager Initialization Flags Decoupling (FEAT-042)
**Spec**: `sdd/specs/decoupling-db-bots-botmanager.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: TASK-283
**Assigned-to**: claude-session

---

## Context

> Two changes in `on_startup`:
> 1. Replace the global `ENABLE_CREWS` reference with `self.enable_crews`.
> 2. Gate `BotConfigStorage` initialization behind `self.enable_registry_bots`
>    (per user's open question answer: "Yes" — skip BotConfigStorage when
>    registry is disabled, spec line 414–416).
> Implements spec Section 3 Module 4.

---

## Scope

Modify the `on_startup` method in `parrot/manager/manager.py` (currently
around lines 743–769).

**NOT in scope**: Any other methods or files.

---

## Files to Modify

| File | Action |
|---|---|
| `parrot/manager/manager.py` | MODIFY |

---

## Change Specification

### 1. Replace global `ENABLE_CREWS` with instance attr

```python
# Before (line ~750):
if ENABLE_CREWS:
    await self.load_crews()

# After:
if self.enable_crews:
    await self.load_crews()
```

### 2. Gate BotConfigStorage init behind enable_registry_bots

```python
# Before (line ~748):
app['bot_config_storage'] = BotConfigStorage()

# After:
if self.enable_registry_bots:
    app['bot_config_storage'] = BotConfigStorage()
```

The net result is that `on_startup` only initializes `BotConfigStorage` when
the registry subsystem is active.

---

## Acceptance Criteria

- [ ] No global `ENABLE_CREWS` reference in `on_startup` — uses `self.enable_crews`
- [ ] `BotConfigStorage()` is **not** instantiated when `enable_registry_bots=False`
- [ ] `BotConfigStorage()` **is** instantiated when `enable_registry_bots=True`
- [ ] `load_crews()` is called when `self.enable_crews=True`
- [ ] `load_crews()` is skipped when `self.enable_crews=False`
- [ ] `ruff check parrot/manager/manager.py` passes

---

## Agent Instructions

1. Read `parrot/manager/manager.py` around lines 743–769 to understand current `on_startup`
2. Apply the two changes per the change spec above
3. Run `ruff check parrot/manager/manager.py` and fix issues
4. Update `sdd/tasks/.index.json` → `"done"`
5. Move this file to `sdd/tasks/completed/TASK-285-on-startup-gating.md`
6. Fill in the Completion Note below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-10
**Notes**: Applied two changes to `on_startup` in `parrot/manager/manager.py`:
1. Gated `BotConfigStorage()` instantiation behind `if self.enable_registry_bots:`
2. Replaced `if ENABLE_CREWS:` with `if self.enable_crews:`
Also auto-fixed two pre-existing ruff F401 warnings (unused imports in a local import).
`ENABLE_CREWS` is retained in the import and `__init__` default — correct as it's the default value for the `enable_crews` param.
