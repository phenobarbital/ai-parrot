# TASK-224: Remove parrot.exceptions Extension from setup.py

**Feature**: Exception Migration — Cython to Pure Python (FEAT-031)
**Spec**: `sdd/specs/exception-migration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: TASK-222
**Assigned-to**: claude-sonnet-4-6

---

## Context

> `setup.py` currently declares `parrot.exceptions` as a Cython `Extension`. Now that
> `parrot/exceptions.py` provides a pure Python implementation, the build extension is
> unnecessary and should be removed to simplify the build process and developer onboarding.

---

## Scope

Edit `setup.py` to remove the `parrot.exceptions` Extension block:

```python
# REMOVE this block entirely:
Extension(
    name='parrot.exceptions',
    sources=['parrot/exceptions.pyx'],
    extra_compile_args=COMPILE_ARGS,
    language="c"
),
```

The two remaining extensions (`parrot.utils.types` and `parrot/utils/parsers/toml`) are retained
unchanged.

**NOT in scope**: Removing the other two extensions, modifying `pyproject.toml`, updating callers,
or deleting Cython artifacts.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `setup.py` | MODIFY | Remove `parrot.exceptions` Extension block |

---

## Implementation Notes

- After removal, `setup.py` must still be syntactically valid Python.
- If `extensions` list has trailing comma issues after removal, fix them.
- Verify `python setup.py build_ext --inplace` still compiles the remaining two extensions
  without error (optional smoke-check; do not run if build toolchain is unavailable).

---

## Acceptance Criteria

- [x] `setup.py` no longer contains `parrot.exceptions` or `exceptions.pyx`
- [x] `setup.py` remains syntactically valid (verified with `python -c "import ast; ast.parse(open('setup.py').read())"`)
- [x] The two remaining extensions (`parrot.utils.types`, `parrot/utils/parsers/toml`) are untouched

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/exception-migration.spec.md` for full context
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
3. **Implement** following the scope and notes above
4. **Verify** all acceptance criteria are met
5. **Move this file** to `sdd/tasks/completed/TASK-224-remove-cython-extension-setup.md`
6. **Update index** → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-07
**Notes**: Removed the `parrot.exceptions` Extension block (5 lines) from `setup.py`. The two remaining extensions (`parrot.utils.types`, `parrot/utils/parsers/toml`) are untouched. Syntax verified with `ast.parse`.

**Deviations from spec**: None.
