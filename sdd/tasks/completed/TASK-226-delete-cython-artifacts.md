# TASK-226: Delete Stale Cython Artifacts

**Feature**: Exception Migration — Cython to Pure Python (FEAT-031)
**Spec**: `sdd/specs/exception-migration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: TASK-222, TASK-223, TASK-224, TASK-225, TASK-227
**Assigned-to**: claude-sonnet-4-6

---

## Context

> Final cleanup task. Once the pure Python implementation is in place, tests pass, and callers
> are updated, the Cython source files and compiled artifacts can be safely removed from the
> source tree.

---

## Scope

Delete the following files:

| File | Reason |
|---|---|
| `parrot/exceptions.pyx` | Replaced by `parrot/exceptions.py` |
| `parrot/exceptions.pxd` | Cython C-level header declarations, no longer needed |
| `parrot/exceptions.pxi` | Superseded by `parrot/exceptions.pyi` (created in TASK-223) |
| `parrot/exceptions.c` | Generated C file from Cython transpilation |
| `parrot/exceptions.cpython-311-x86_64-linux-gnu.so` | Compiled binary, replaced by `.py` |

**Pre-condition check**: Before deleting, confirm:
1. `parrot/exceptions.py` exists (TASK-222 completed)
2. `parrot/exceptions.pyi` exists (TASK-223 completed)
3. All tests in `tests/test_exceptions.py` pass (TASK-227 completed)
4. Full pytest suite passes (TASK-225 completed)

**NOT in scope**: Any other files or directories.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/exceptions.pyx` | DELETE |
| `parrot/exceptions.pxd` | DELETE |
| `parrot/exceptions.pxi` | DELETE |
| `parrot/exceptions.c` | DELETE |
| `parrot/exceptions.cpython-311-x86_64-linux-gnu.so` | DELETE |

---

## Implementation Notes

- Use the file deletion tools available in the environment — do NOT use `rm -rf`.
- After deletion, run `python -c "from parrot.exceptions import ParrotError; print('OK')"` to
  confirm the pure Python module loads correctly.
- CPython prefers `.so` over `.py` in the same directory, so the `.so` must be deleted before
  the pure Python implementation is active at runtime.

---

## Acceptance Criteria

- [ ] `parrot/exceptions.pyx` does not exist
- [ ] `parrot/exceptions.pxd` does not exist
- [ ] `parrot/exceptions.pxi` does not exist
- [ ] `parrot/exceptions.c` does not exist
- [ ] `parrot/exceptions.cpython-311-x86_64-linux-gnu.so` does not exist
- [ ] `parrot/exceptions.py` still exists
- [ ] `parrot/exceptions.pyi` still exists
- [ ] `from parrot.exceptions import ParrotError` still works after deletion
- [ ] `pytest tests/test_exceptions.py -v` passes after deletion

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/exception-migration.spec.md` for full context
2. **Confirm all dependencies** (TASK-222 through TASK-225, TASK-227) are `done`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Delete** the five listed files
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-226-delete-cython-artifacts.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-07
**Notes**:
- Deleted all 5 artifacts: `exceptions.pyx`, `exceptions.pxd`, `exceptions.pxi`,
  `exceptions.c`, `exceptions.cpython-311-x86_64-linux-gnu.so`.
- Confirmed `parrot/exceptions.py` is now the active module:
  `import parrot.exceptions; __file__` → `parrot/exceptions.py`.
- `pytest tests/test_exceptions.py -v` → 20 passed against the live pure Python module.
- Only `parrot/exceptions.py` and `parrot/exceptions.pyi` remain in the directory.

**Deviations from spec**: None.
