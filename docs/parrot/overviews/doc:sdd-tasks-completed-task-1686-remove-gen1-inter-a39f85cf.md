---
type: Wiki Overview
title: 'TASK-1686: Delete Gen 1 legacy O365 interactive-auth (orphaned)'
id: doc:sdd-tasks-completed-task-1686-remove-gen1-interactive-auth-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 6. The Gen 1 device-code auth (`RemoteAuthManager`
  + REST handlers)
relates_to:
- concept: mod:parrot.handlers
  rel: mentions
- concept: mod:parrot.services
  rel: mentions
---

# TASK-1686: Delete Gen 1 legacy O365 interactive-auth (orphaned)

**Feature**: FEAT-266 — O365 Auth Homologation
**Spec**: `sdd/specs/o365-auth-homologation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 6. The Gen 1 device-code auth (`RemoteAuthManager` + REST handlers)
is dead code — all `app.py` wiring is commented out and there are no external consumers. Its
only useful capability (device-code) is replaced by TASK-1683's resolver. This task removes it.

---

## Scope

- Delete `packages/ai-parrot-server/src/parrot/services/o365_remote_auth.py`
  (`RemoteAuthManager`, `RemoteAuthSession`).
- Delete `packages/ai-parrot-server/src/parrot/handlers/o365_auth.py`
  (`O365InteractiveAuthSessions`, `O365InteractiveAuthSessionDetail`, `_get_manager`).
- Remove the COMMENTED Gen 1 blocks in `app.py` only:
  - the commented imports near lines ~31-34 (`O365InteractiveAuthSessions`,
    `O365InteractiveAuthSessionDetail`, `RemoteAuthManager`);
  - the commented `o365_auth_manager` / `add_view('/api/v1/o365/auth/sessions...')` /
    shutdown blocks near lines ~166-181.
- Before deleting, grep-confirm no other (non-comment, non-test) importer references these symbols.

**NOT in scope**: any new device-code code (TASK-1681..1685), and ANY non-Gen1 change in
`app.py` — in particular do NOT touch the unrelated logging refactor present in the working tree.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/o365_remote_auth.py` | DELETE | Gen 1 manager |
| `packages/ai-parrot-server/src/parrot/handlers/o365_auth.py` | DELETE | Gen 1 handlers |
| `app.py` | MODIFY | remove ONLY the commented Gen 1 blocks |

---

## Codebase Contract (Anti-Hallucination)

### Symbols being removed (verify no live importer first)
```python
# packages/ai-parrot-server/src/parrot/services/o365_remote_auth.py
class RemoteAuthManager: ...          # line 52
class RemoteAuthSession: ...          # line 16
__all__ = ["RemoteAuthManager", "RemoteAuthSession"]   # line 235

# packages/ai-parrot-server/src/parrot/handlers/o365_auth.py
from ..services.o365_remote_auth import RemoteAuthManager   # line 7  (the ONLY live importer)
class O365InteractiveAuthSessions(BaseView): ...      # line 20
class O365InteractiveAuthSessionDetail(BaseView): ... # line 62
```

### Verification command (run FIRST)
```bash
grep -rn "RemoteAuthManager\|O365InteractiveAuthSession\|o365_remote_auth\|o365_auth" \
  packages/ app.py --include=*.py | grep -v "^\s*#" | grep -v "/tests/"
# Expect: only the handler↔manager pair (both being deleted) + app.py commented lines.
```

### Does NOT Exist
- ~~Any live route registered for `/api/v1/o365/auth/sessions`~~ — wiring is fully commented in `app.py`.
- ~~Persisted Gen 1 session state~~ — sessions were in-memory; nothing to migrate.

---

## Implementation Notes

### Key Constraints
- Surgical edit on `app.py`: remove ONLY the commented Gen 1 import/route/shutdown lines.
  Leave every other line — especially the unrelated logging changes — untouched.
- If the grep finds an unexpected live importer, STOP and note it in the completion note rather
  than deleting.

### References in Codebase
- Spec §1 Problem Statement + §3 Module 6 + §7 (gotcha about `app.py`).

---

## Acceptance Criteria

- [ ] `o365_remote_auth.py` and `o365_auth.py` are deleted.
- [ ] `app.py` no longer contains the commented Gen 1 import/route/shutdown blocks; all other lines unchanged.
- [ ] `grep` confirms no remaining live reference to the deleted symbols (outside tests).
- [ ] `import` of the app module / server package still succeeds (no dangling import).
- [ ] `ruff check app.py` clean (no new issues introduced).

---

## Test Specification

```python
import importlib, pytest

def test_gen1_modules_removed():
    for mod in ("parrot.services.o365_remote_auth", "parrot.handlers.o365_auth"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(mod)
```

---

## Agent Instructions
Standard SDD flow. Run the verification grep BEFORE deleting. Independent of other tasks —
can run first or last.

## Completion Note
Ran the required verification grep first — confirmed the only live
(non-comment, non-test) reference to the Gen 1 symbols was the
handler↔manager pair itself (`handlers/o365_auth.py:7` importing
`RemoteAuthManager` from `services/o365_remote_auth.py`), exactly as the
task predicted. Deleted both files (`git rm`). Surgically removed ONLY the
commented Gen 1 blocks in `app.py`: the 3-line commented import block
(former lines ~30-34) and the commented manager-assignment + two
`add_view` blocks (former lines ~166-176). Left every other line —
including the unrelated uncommitted logging refactor — untouched.

**One discrepancy vs. the task's assumption, NOT deleted (per "STOP and
note" instruction):** `app.py`'s `on_shutdown()` hook contains an
**uncommented** `if manager := app.get('o365_auth_manager'): await
manager.shutdown()` (originally line 355, now ~338). The task's file table
description implied this shutdown reference lived within the same
commented 166-181 region; in reality it's a separate, non-commented block
elsewhere in the file. It was ALREADY inert before this change (nothing
ever set `app['o365_auth_manager']` since its only setter was already
commented out prior to this feature), so it remains 100% dead code that
does not import or reference any deleted symbol by name (duck-typed
`.shutdown()` call via a string key `.get()`). Left untouched per "remove
ONLY the commented Gen 1 blocks... do NOT touch... unrelated" — flagging
here as a candidate for a future trivial cleanup, not blocking this task's
acceptance criteria (no dangling import, `grep` clean of live symbol
references).

Added `packages/ai-parrot-server/tests/unit/test_gen1_o365_auth_removed.py`
(from the task's own Test Specification; not listed in the file table but
implied by it) asserting `ModuleNotFoundError` for both deleted modules.
**Test-harness caveat:** this worktree shares a `.venv` with the main repo
checkout via an editable install; `parrot.services`/`parrot.handlers` are
PEP 420 namespace packages merged across BOTH the worktree's and the main
repo's `src/` roots. Since the main repo checkout (pre-merge) still
physically has the old files, the merged namespace falls through to them
and the test spuriously passes-as-found in that specific shared-venv
setup. Verified the deletion is correct via (1) the required grep — clean;
(2) a sys.path-isolated repro excluding all non-worktree paths — both
imports correctly raise `ModuleNotFoundError`. This artifact disappears in
any real single-checkout environment (CI, or this repo post-merge) where
only one copy of `ai-parrot-server/src` is ever on the path.

`ruff check app.py` clean (pre-existing unrelated `tasker` F841 finding
confirmed present on `dev`, untouched by this task).
