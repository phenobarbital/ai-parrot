# TASK-873: Update FileManager Example for Toolkit API

**Feature**: FEAT-127 — FileManagerTool Migration to Toolkit
**Spec**: `sdd/specs/filemanagertool-migration-toolkit.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-869, TASK-870
**Assigned-to**: unassigned

---

## Context

The existing `examples/tool/fs.py` demonstrates `FileManagerTool` with the old multi-operation dispatch pattern. This task updates the example to showcase `FileManagerToolkit`, demonstrating how individual tools are called directly with focused parameters.

Implements Spec §3 Module 5 (Example Update).

---

## Scope

- Update `examples/tool/fs.py` to demonstrate `FileManagerToolkit` usage.
- Show: creating the toolkit, listing tools, calling individual methods directly.
- Keep the old `FileManagerTool` usage as a commented-out "legacy" section for reference.

**NOT in scope**:
- Creating new example files.
- Implementing or modifying the toolkit (TASK-869).
- Tests (TASK-872).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/tool/fs.py` | MODIFY | Replace `FileManagerTool` demo with `FileManagerToolkit` demo |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools import FileManagerToolkit  # available after TASK-870
from navconfig import BASE_DIR               # verified: used in examples/tool/fs.py:2
```

### Existing Signatures to Use
```python
# examples/tool/fs.py (current content — line 1-19)
import asyncio
from navconfig import BASE_DIR
from parrot.tools import FileManagerTool

async def sample_usage():
    file_tool = FileManagerTool(manager_type="fs")
    result = await file_tool._execute(
        operation="list", path=BASE_DIR.joinpath("docs/"), pattern="*.md"
    )
    print(result)

if __name__ == "__main__":
    asyncio.run(sample_usage())
```

### Does NOT Exist
- ~~`FileManagerToolkit.execute()`~~ — toolkits don't have execute(); call individual methods
- ~~`FileManagerToolkit._execute()`~~ — toolkits don't have _execute()

---

## Implementation Notes

### Pattern to Follow
```python
import asyncio
from navconfig import BASE_DIR
from parrot.tools import FileManagerToolkit

async def sample_usage():
    # Create toolkit with local filesystem backend
    toolkit = FileManagerToolkit(manager_type="fs")

    # List available tools
    print("Available tools:", toolkit.list_tool_names())

    # Call operations directly — each is a focused tool
    result = await toolkit.list_files(
        path=str(BASE_DIR / "docs"), pattern="*.md"
    )
    print("Files found:", result["count"])

    # Create a file
    result = await toolkit.create_file(
        path="output/hello.txt", content="Hello from FileManagerToolkit!"
    )
    print("Created:", result["path"])

    # Check existence
    result = await toolkit.file_exists(path="output/hello.txt")
    print("Exists:", result["exists"])

if __name__ == "__main__":
    asyncio.run(sample_usage())
```

### Key Constraints
- Example must be runnable standalone (`python examples/tool/fs.py`).
- Keep it simple — demonstrate the API, not edge cases.
- Show the improvement: no `operation` field needed, each call is self-explanatory.

### References in Codebase
- `examples/tool/fs.py` — current file to modify

---

## Acceptance Criteria

- [ ] `examples/tool/fs.py` demonstrates `FileManagerToolkit`
- [ ] Example shows at least 3 different operations (list, create, exists)
- [ ] Example is syntactically correct and runnable
- [ ] No references to removed/non-existent APIs

---

## Test Specification

No automated tests for examples. Manual verification:
```bash
# Should run without import errors (filesystem ops may fail depending on paths)
source .venv/bin/activate && python -c "import ast; ast.parse(open('examples/tool/fs.py').read()); print('Syntax OK')"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filemanagertool-migration-toolkit.spec.md` for full context
2. **Check dependencies** — verify TASK-869 and TASK-870 are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `FileManagerToolkit` is importable
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** — update the example file
6. **Verify** syntax is correct
7. **Move this file** to `tasks/completed/TASK-873-filemanager-toolkit-example.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude claude-sonnet-4-5)
**Date**: 2026-04-27
**Notes**: Updated `examples/tool/fs.py` to demonstrate `FileManagerToolkit`.
The example shows: `list_files`, `create_file`, `file_exists`, `get_file_metadata`,
and `delete_file` — five distinct operations with focused parameters. The old
`FileManagerTool` usage is preserved as a commented-out legacy section for reference.
Syntax verified via `ast.parse`. Example is runnable as a standalone script.

**Deviations from spec**: none

**Deviations from spec**: none | describe if any
