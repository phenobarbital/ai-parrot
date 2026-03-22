# TASK-394: FlowtTask Isolation

**Feature**: runtime-dependency-reduction
**Spec**: `sdd/specs/runtime-dependency-reduction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-386, TASK-387
**Assigned-to**: unassigned

---

## Context

`flowtask` is currently a hard dependency that transitively pulls `asyncdb[all]`, which installs MySQL drivers requiring `libmysqlclient-dev`. This is the single biggest pain point for users. Flowtask is a DAG task execution tool used by a specific subset of users and must become optional.

Implements: Spec Module 9 — FlowtTask Isolation.

---

## Scope

- Ensure `parrot/tools/flowtask/tool.py` uses `lazy_import("flowtask", extra="flowtask")` consistently (already partially lazy via importlib).
- Ensure `parrot/tools/flowtask/__init__.py` is importable without flowtask installed (may need to guard exports).
- Standardize the existing importlib pattern to use `parrot._imports.lazy_import()`.
- Verify that `flowtask` was removed from hard deps (done in TASK-387) and is only in `[flowtask]` extra.
- Search for any other files that import flowtask and convert them.

**NOT in scope**: Upstream changes to flowtask package itself.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/flowtask/__init__.py` | MODIFY | Guard exports, lazy-import |
| `parrot/tools/flowtask/tool.py` | MODIFY | Standardize to lazy_import() |
| Any other files importing flowtask | MODIFY | Lazy-import |

---

## Implementation Notes

### Current State
`parrot/tools/flowtask/tool.py` already uses `importlib.import_module` in some places. Standardize all flowtask imports to use `lazy_import()`.

### Pattern to Follow
```python
from parrot._imports import lazy_import

class FlowtaskTool:
    def run_task(self, task_name: str):
        ft = lazy_import("flowtask", extra="flowtask")
        # use ft...
```

### Key Constraints
- The `__init__.py` must not crash on import even without flowtask
- All flowtask-specific classes/functions should be lazy
- Error message: `pip install ai-parrot[flowtask]`

---

## Acceptance Criteria

- [ ] `from parrot.tools.flowtask import *` works without flowtask installed (exports may be empty/guarded)
- [ ] `import parrot.tools.flowtask.tool` works without flowtask installed
- [ ] Flowtask tools work correctly when flowtask is installed
- [ ] Missing dep raises: `pip install ai-parrot[flowtask]`
- [ ] No `libmysqlclient-dev` requirement in core install path
- [ ] All existing flowtask tests pass with flowtask installed

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-386 and TASK-387 are completed
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Read existing flowtask code** to understand current import patterns
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-394-flowtask-isolation.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
