# TASK-870: Update parrot.tools Exports for FileManagerToolkit

**Feature**: FEAT-127 — FileManagerTool Migration to Toolkit
**Spec**: `sdd/specs/filemanagertool-migration-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-869
**Assigned-to**: unassigned

---

## Context

After `FileManagerToolkit` is implemented (TASK-869), it must be importable via `from parrot.tools import FileManagerToolkit`. This task updates the `parrot/tools/__init__.py` module to add the new toolkit to the lazy-load map and public `__all__`.

Implements Spec §3 Module 2 (Exports & Registry Update).

---

## Scope

- Add `"FileManagerToolkit"` to `__all__` tuple in `packages/ai-parrot/src/parrot/tools/__init__.py`.
- Add `"FileManagerToolkit": ".filemanager"` to `_LAZY_CORE_TOOLS` dict.
- Keep existing `"FileManagerTool"` and `"FileManagerFactory"` entries unchanged.

**NOT in scope**:
- Implementing the toolkit class (TASK-869).
- Modifying `parrot_tools/__init__.py` registry (TASK-871).
- Tests (TASK-872).
- Example update (TASK-873).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/__init__.py` | MODIFY | Add `FileManagerToolkit` to `__all__` and `_LAZY_CORE_TOOLS` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No new imports needed — modifying existing module exports only.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/__init__.py

# __all__ tuple — line 207
__all__ = (
    # ...
    "FileManagerTool",      # existing — keep
    "FileManagerFactory",   # existing — keep
    # ...
)

# _LAZY_CORE_TOOLS dict — line 232
_LAZY_CORE_TOOLS = {
    # ...
    "FileManagerTool": ".filemanager",     # line 238 — keep
    "FileManagerFactory": ".filemanager",  # line 239 — keep
    # ...
}
```

### Does NOT Exist
- ~~`_LAZY_CORE_TOOLS["FileManagerToolkit"]`~~ — does not exist yet (this task adds it)
- ~~`"FileManagerToolkit"` in `__all__`~~ — not yet present (this task adds it)

---

## Implementation Notes

### Key Constraints
- Add `"FileManagerToolkit"` AFTER `"FileManagerFactory"` in both `__all__` and `_LAZY_CORE_TOOLS` to maintain logical grouping.
- The value in `_LAZY_CORE_TOOLS` must be `".filemanager"` — same module as `FileManagerTool`.
- Do NOT remove or modify any existing entries.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/__init__.py` — the file to modify

---

## Acceptance Criteria

- [ ] `from parrot.tools import FileManagerToolkit` works without error
- [ ] `from parrot.tools import FileManagerTool` still works (backward compat)
- [ ] `from parrot.tools import FileManagerFactory` still works
- [ ] `"FileManagerToolkit"` appears in `parrot.tools.__all__`
- [ ] No other changes to `__init__.py`

---

## Test Specification

```python
def test_import_toolkit():
    from parrot.tools import FileManagerToolkit
    assert FileManagerToolkit is not None

def test_import_legacy_tool():
    from parrot.tools import FileManagerTool
    assert FileManagerTool is not None

def test_import_factory():
    from parrot.tools import FileManagerFactory
    assert FileManagerFactory is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filemanagertool-migration-toolkit.spec.md` for full context
2. **Check dependencies** — verify TASK-869 is in `tasks/completed/`
3. **Verify the Codebase Contract** — read `packages/ai-parrot/src/parrot/tools/__init__.py` to confirm current `__all__` and `_LAZY_CORE_TOOLS` match what's listed above
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** — add two entries
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-870-filemanager-toolkit-exports.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
