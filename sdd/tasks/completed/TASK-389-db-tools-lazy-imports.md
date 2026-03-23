# TASK-389: Database/Query Tools Lazy Imports

**Feature**: runtime-dependency-reduction
**Spec**: `sdd/specs/runtime-dependency-reduction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-386, TASK-387
**Assigned-to**: unassigned

---

## Context

Database and query tools are the most widespread users of `asyncdb` and `querysource` imports. Since `querysource` is now in the `[db]` extra, all 7+ tool files that import it must be converted to lazy imports. These tools should still work perfectly when the `[db]` extra is installed, but the module should be importable without it.

Implements: Spec Module 4 — Database/Query Tools Lazy Imports.

---

## Scope

- Convert top-level `asyncdb` and `querysource` imports to `lazy_import()` in:
  - `parrot/tools/db.py`
  - `parrot/tools/querytoolkit.py`
  - `parrot/tools/qsource.py`
  - `parrot/tools/databasequery.py`
  - `parrot/tools/dataset_manager/sources/sql.py`
  - `parrot/tools/dataset_manager/sources/table.py`
  - `parrot/tools/dataset_manager/tool.py`
  - `parrot/tools/dataset_manager/sources/query_slug.py`
  - `parrot/tools/nextstop/base.py`
  - `parrot/tools/products/__init__.py`
- Use `lazy_import("querysource", extra="db")` and `lazy_import("asyncdb", extra="db")`.
- Use `TYPE_CHECKING` blocks for type annotations.
- Note: `asyncdb[default]` is still in core, so basic asyncdb import will work. The lazy import is primarily for `querysource` and any asyncdb submodules that require non-default extras.

**NOT in scope**: Handler/interface files (TASK-390). Bot DB modules (TASK-396).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/db.py` | MODIFY | Lazy-import asyncdb/querysource |
| `parrot/tools/querytoolkit.py` | MODIFY | Lazy-import querysource |
| `parrot/tools/qsource.py` | MODIFY | Lazy-import querysource |
| `parrot/tools/databasequery.py` | MODIFY | Lazy-import asyncdb/querysource |
| `parrot/tools/dataset_manager/sources/sql.py` | MODIFY | Lazy-import asyncdb |
| `parrot/tools/dataset_manager/sources/table.py` | MODIFY | Lazy-import asyncdb |
| `parrot/tools/dataset_manager/tool.py` | MODIFY | Lazy-import querysource |
| `parrot/tools/dataset_manager/sources/query_slug.py` | MODIFY | Lazy-import querysource |
| `parrot/tools/nextstop/base.py` | MODIFY | Lazy-import asyncdb/querysource |
| `parrot/tools/products/__init__.py` | MODIFY | Lazy-import asyncdb/querysource |

---

## Implementation Notes

### Pattern to Follow
```python
from __future__ import annotations
from typing import TYPE_CHECKING
from parrot._imports import lazy_import

if TYPE_CHECKING:
    from querysource import QS

class DatabaseQueryTool:
    def __init__(self):
        # Lazy import at init or method level
        qs_module = lazy_import("querysource", extra="db")
        self._qs = qs_module.QS
```

### Key Constraints
- Each file must be independently importable without querysource/asyncdb extras
- `asyncdb[default]` is in core — only querysource and advanced asyncdb submodules need lazy import
- Preserve all existing tool functionality
- Test each file individually after refactoring

### References in Codebase
- `parrot/tools/qsource.py` — already has some lazy querysource patterns (standardize)
- `parrot/tools/dataset_manager/tool.py` — already has some lazy patterns

---

## Acceptance Criteria

- [ ] All listed files importable without `querysource` installed
- [ ] All DB tools work correctly when `querysource` is installed
- [ ] Missing querysource raises: `pip install ai-parrot[db]`
- [ ] All existing tests pass: `pytest tests/ -v -k "db or query or dataset"` (with deps installed)

---

## Test Specification

```python
# Verify each module is importable without querysource
import pytest
from unittest.mock import patch
import builtins

@pytest.fixture
def block_querysource():
    original = builtins.__import__
    def blocked(name, *args, **kwargs):
        if name == "querysource" or name.startswith("querysource."):
            raise ImportError(f"No module named '{name}'")
        return original(name, *args, **kwargs)
    with patch("builtins.__import__", side_effect=blocked):
        yield

class TestDBToolsLazyImports:
    def test_db_tool_importable(self, block_querysource):
        import importlib, parrot.tools.db
        importlib.reload(parrot.tools.db)

    def test_querytoolkit_importable(self, block_querysource):
        import importlib, parrot.tools.querytoolkit
        importlib.reload(parrot.tools.querytoolkit)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-386 and TASK-387 are completed
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Read each file** before modifying — understand how asyncdb/querysource are used
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-389-db-tools-lazy-imports.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
