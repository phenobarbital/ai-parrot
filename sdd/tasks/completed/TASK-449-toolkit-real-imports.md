# TASK-449: Replace stubs with real AbstractToolkit and tool_schema imports

**Feature**: refactor-workingmemorytoolkit
**Spec**: `sdd/specs/refactor-workingmemorytoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-448
**Assigned-to**: unassigned

---

## Context

Per the spec (Module 3), `tool.py` still contains local stub definitions for `AbstractToolkit` and `tool_schema`. These must be replaced with the real framework imports. Additionally, the module-level `logger` must be replaced with `self.logger` in `WorkingMemoryToolkit`.

---

## Scope

- Remove the stub `tool_schema` function from `tool.py`
- Remove the stub `AbstractToolkit` class from `tool.py`
- Add `from parrot.tools import AbstractToolkit, tool_schema` (or the direct module imports)
- Replace `logger = logging.getLogger("working_memory")` with `self.logger` usage in `WorkingMemoryToolkit`
  - Initialize `self.logger = logging.getLogger(__name__)` in `__init__` (if not inherited from `AbstractToolkit`)
  - Replace any `logger.warning(...)` calls with `self.logger.warning(...)`
- Add Google-style docstring to `WorkingMemoryToolkit` class (purpose/description only)
- Remove any remaining comments about "stub" or "standalone development"
- Clean up the module docstring to remove architecture diagram (it's in the spec)

**NOT in scope**: Changing `__init__.py`, test relocation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | MODIFY | Replace stubs with real imports, use self.logger |

---

## Implementation Notes

### Correct Import Pattern
```python
# Option 1: From package (recommended)
from parrot.tools import AbstractToolkit, tool_schema

# Option 2: Direct module imports
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.decorators import tool_schema
```

### Logger Pattern
```python
class WorkingMemoryToolkit(AbstractToolkit):
    def __init__(self, ...):
        super().__init__(**kwargs)
        self.logger = logging.getLogger(__name__)
        # ... rest of init
```

### Key Constraints
- Check if `AbstractToolkit` already provides `self.logger` — if yes, don't duplicate
- `tool.py` should now ONLY contain the `WorkingMemoryToolkit` class and its imports
- Verify `@tool_schema` decorator from the real framework works the same as the stub

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/toolkit.py` — real `AbstractToolkit`
- `packages/ai-parrot/src/parrot/tools/decorators.py` — real `tool_schema`
- `packages/ai-parrot-tools/src/parrot_tools/docker/toolkit.py` — example of real usage

---

## Acceptance Criteria

- [ ] No stub `AbstractToolkit` or `tool_schema` definitions in `tool.py`
- [ ] `WorkingMemoryToolkit` inherits from the real `AbstractToolkit`
- [ ] `@tool_schema` is the real decorator from `parrot.tools.decorators`
- [ ] `self.logger` used instead of module-level `logger`
- [ ] No "stub" or "standalone development" comments remain
- [ ] `tool.py` contains only `WorkingMemoryToolkit` class + imports
- [ ] `python -c "from parrot.tools.working_memory.tool import WorkingMemoryToolkit; print(WorkingMemoryToolkit.__bases__)"` shows real AbstractToolkit
- [ ] All existing tests still pass

---

## Test Specification

```python
from parrot.tools.working_memory.tool import WorkingMemoryToolkit
from parrot.tools.toolkit import AbstractToolkit

assert issubclass(WorkingMemoryToolkit, AbstractToolkit)
tk = WorkingMemoryToolkit()
assert hasattr(tk, 'logger')
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-449-toolkit-real-imports.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-03-26
**Notes**: Replaced stub AbstractToolkit and tool_schema with real imports from parrot.tools.toolkit and parrot.tools.decorators. AbstractToolkit already provides self.logger so no duplication needed. Replaced logger.warning with self.logger.warning in compute_and_store.

**Deviations from spec**: none
