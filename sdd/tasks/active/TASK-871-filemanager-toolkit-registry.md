# TASK-871: Update parrot_tools Registry for FileManagerToolkit

**Feature**: FEAT-127 — FileManagerTool Migration to Toolkit
**Spec**: `sdd/specs/filemanagertool-migration-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-869
**Assigned-to**: unassigned

---

## Context

The `parrot_tools` package maintains a `TOOL_REGISTRY` dict that maps string keys to dotted class paths. This registry enables lazy tool resolution by name. This task adds a `"file_manager_toolkit"` entry pointing to the new `FileManagerToolkit` class while keeping the existing `"file_manager"` entry for backward compatibility.

Implements Spec §3 Module 3 (parrot_tools Registry Update).

---

## Scope

- Add `"file_manager_toolkit": "parrot.tools.filemanager.FileManagerToolkit"` to `TOOL_REGISTRY` in `packages/ai-parrot-tools/src/parrot_tools/__init__.py`.
- Keep the existing `"file_manager": "parrot.tools.filemanager.FileManagerTool"` entry unchanged.

**NOT in scope**:
- Implementing the toolkit class (TASK-869).
- Modifying `parrot/tools/__init__.py` (TASK-870).
- Tests (TASK-872).
- Example update (TASK-873).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Add `file_manager_toolkit` entry to `TOOL_REGISTRY` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No new imports — modifying an existing dict literal only.
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py
# TOOL_REGISTRY dict (exact location varies — search for "file_manager")
"file_manager": "parrot.tools.filemanager.FileManagerTool",  # line ~51 — keep unchanged
```

### Does NOT Exist
- ~~`TOOL_REGISTRY["file_manager_toolkit"]`~~ — does not exist yet (this task adds it)
- ~~`TOOL_REGISTRY["fs_toolkit"]`~~ — does not exist; do NOT use this key

---

## Implementation Notes

### Key Constraints
- Add the new entry directly after the existing `"file_manager"` entry for logical grouping.
- Use `"file_manager_toolkit"` as the key (NOT `"fs_toolkit"` or `"filemanager_toolkit"`).
- The value must be `"parrot.tools.filemanager.FileManagerToolkit"` (same module path).
- Do NOT remove the existing `"file_manager"` entry.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/__init__.py` — the file to modify

---

## Acceptance Criteria

- [ ] `TOOL_REGISTRY["file_manager_toolkit"]` resolves to `"parrot.tools.filemanager.FileManagerToolkit"`
- [ ] `TOOL_REGISTRY["file_manager"]` still resolves to `"parrot.tools.filemanager.FileManagerTool"` (unchanged)
- [ ] No other changes to the file

---

## Test Specification

```python
def test_registry_has_toolkit():
    from parrot_tools import TOOL_REGISTRY
    assert "file_manager_toolkit" in TOOL_REGISTRY
    assert TOOL_REGISTRY["file_manager_toolkit"] == "parrot.tools.filemanager.FileManagerToolkit"

def test_registry_has_legacy_tool():
    from parrot_tools import TOOL_REGISTRY
    assert "file_manager" in TOOL_REGISTRY
    assert TOOL_REGISTRY["file_manager"] == "parrot.tools.filemanager.FileManagerTool"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filemanagertool-migration-toolkit.spec.md` for full context
2. **Check dependencies** — verify TASK-869 is in `tasks/completed/`
3. **Verify the Codebase Contract** — read `packages/ai-parrot-tools/src/parrot_tools/__init__.py` and locate `TOOL_REGISTRY` and the `"file_manager"` entry
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** — add one dict entry
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-871-filemanager-toolkit-registry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
