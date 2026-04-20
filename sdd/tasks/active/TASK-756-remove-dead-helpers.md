# TASK-756: Remove dead helpers (`_nav_run_query`, `_nav_run_one`, `_nav_execute`, `_nav_build_update`)

**Feature**: FEAT-107 — NavigatorToolkit Method Migration to PostgresToolkit CRUD
**Spec**: `sdd/specs/navigator-toolkit-method-migration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-749, TASK-750, TASK-751, TASK-752, TASK-753, TASK-754, TASK-755
**Assigned-to**: unassigned

---

## Context

Implements **Module 9** of the spec. After every write and SELECT is
migrated, the four private helpers that drove raw SQL are dead code.
This task proves they are unreferenced, deletes them, and removes the
accompanying docstring block.

---

## Scope

- Confirm zero remaining call sites:
  ```bash
  grep -n "_nav_run_query\|_nav_run_one\|_nav_execute\|_nav_build_update" \
    packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py
  # expected: 0 matches (excluding the method definitions themselves)
  ```
- Delete the four method bodies:
  - `_nav_run_query` (~line 157)
  - `_nav_run_one` (~line 165)
  - `_nav_execute` (~line 173)
  - `_nav_build_update` (~line 297)
- Remove the accompanying docstring block at lines 149-155 that
  references the deleted helpers.
- Run the full test suite to confirm nothing imports them:
  `pytest packages/ai-parrot-tools/tests/unit/ -v`.

**NOT in scope**: any further behavioural change, any authorization
helper edit, any new tests (the TASK-748 unit tests for
`hasattr(…) is False` are the final guard).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` | MODIFY | Delete four helpers + docstring block |

---

## Codebase Contract (Anti-Hallucination)

### Verified Signatures (to delete)
```python
# packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py
async def _nav_run_query(self, sql, params=None) -> list: ...           # 157
async def _nav_run_one(self, sql, params=None) -> Optional[dict]: ...   # 165
async def _nav_execute(self, sql, params=None) -> Any: ...              # 173
async def _nav_build_update(self, table, pk_col, pk_val, data,
    confirm_execution=False, include_updated_at=False) -> dict: ...     # 297
```

### Does NOT Exist (do not delete)
- ~~`_check_program_access` / `_check_module_access` / other `_check_*`~~ — **keep**.
- ~~`_load_user_permissions`~~ — **keep** (orthogonal to migration).
- ~~`_resolve_program_id` / `_resolve_module_id` / `_resolve_dashboard_id` / `_resolve_client_ids`~~ — **keep**.

---

## Implementation Notes

### Pre-flight Check
Before deleting, run:
```bash
grep -rn "_nav_run_query\|_nav_run_one\|_nav_execute\|_nav_build_update" packages/ai-parrot-tools/
```
This must return **only** matches in:
- `src/parrot_tools/navigator/toolkit.py` (the definitions themselves), and
- `tests/unit/test_navigator_toolkit_baseline.py` (the `hasattr(…) is False` assertions from TASK-748).

If any production call site remains, STOP and re-run the relevant
migration task.

### Post-delete Check
- `python -m py_compile packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py`
- `pytest packages/ai-parrot-tools/tests/unit/ -v`
- `ruff check packages/ai-parrot-tools/src/parrot_tools/navigator/`

---

## Acceptance Criteria

- [ ] `grep -c "_nav_run_query\|_nav_run_one\|_nav_execute\|_nav_build_update" toolkit.py` returns **0**.
- [ ] `hasattr(NavigatorToolkit, "_nav_run_query") is False` (and for the other three).
- [ ] `python -m py_compile toolkit.py` succeeds.
- [ ] All existing unit tests still pass.
- [ ] `ruff check` clean.
- [ ] `get_tools()` snapshot still green.

---

## Test Specification

Required (spec §4 — already scaffolded in TASK-748 or added here):
- `test_toolkit_has_no_nav_run_query`
- `test_toolkit_has_no_nav_run_one`
- `test_toolkit_has_no_nav_execute`
- `test_toolkit_has_no_nav_build_update`

---

## Agent Instructions

Standard. This is the simplest task mechanically but the one most
likely to fail if a prior task left a stale call site — treat a
non-zero grep count as a blocker and fix it upstream, not here.
