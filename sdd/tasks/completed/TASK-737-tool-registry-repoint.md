# TASK-737: Repoint `TOOL_REGISTRY["database_query"]` to the new path

**Feature**: databasetoolkit-clash
**Spec**: `sdd/specs/databasetoolkit-clash.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-733, TASK-734
**Assigned-to**: unassigned

---

## Context

After TASK-734 the legacy `DatabaseQueryTool` lives at
`parrot.tools.databasequery.tool.DatabaseQueryTool` (with a re-export at
`parrot.tools.databasequery.DatabaseQueryTool`). The `TOOL_REGISTRY`
entry still points at `parrot_tools.databasequery.DatabaseQueryTool` —
which works via the compat shim, but the canonical entry should reflect
the new home.

This task repoints the registry and confirms the
`_ParrotToolsRedirector` does not hijack the new path.

Implements **Module 6** of the spec.

---

## Scope

- Update `packages/ai-parrot-tools/src/parrot_tools/__init__.py:112`:
  ```python
  "database_query": "parrot.tools.databasequery.DatabaseQueryTool",
  ```
  (was `"parrot_tools.databasequery.DatabaseQueryTool"`).
- Verify `_ParrotToolsRedirector` in
  `packages/ai-parrot/src/parrot/tools/__init__.py:50` does NOT hijack
  `parrot.tools.databasequery.*` imports. Add a single sanity import
  check (manual, not a test): `python -c "import parrot.tools.databasequery; print(parrot.tools.databasequery.__file__)"` must print a path under `packages/ai-parrot/src/parrot/tools/databasequery/__init__.py`, NOT `packages/ai-parrot-tools/src/parrot_tools/...`.
- DO NOT modify `parrot/tools/__init__.py` — `_CORE_SUBMODULES` is a
  glob computed at import time; the new directory and the
  `database.py` shim file (TASK-736) are picked up automatically.

**NOT in scope**:
- Tests (TASK-738).
- Adding new registry entries.
- Cleaning up the unrelated stale imports
  (`parrot.tools.database.pg`, `parrot.tools.database.bq` in
  `parrot/bots/database/abstract.py:45-46`) — those are dead code from
  before FEAT-105 and should be addressed in a separate cleanup spec.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Repoint line 112 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# After TASK-734
from parrot.tools.databasequery import DatabaseQueryTool
# (re-exported by parrot/tools/databasequery/__init__.py from .tool)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py:112 — current
"database_query": "parrot_tools.databasequery.DatabaseQueryTool",
# Must become:
"database_query": "parrot.tools.databasequery.DatabaseQueryTool",

# packages/ai-parrot/src/parrot/tools/__init__.py:50-103
class _ParrotToolsRedirector(importlib.abc.MetaPathFinder):
    _PREFIX = "parrot.tools."                              # line 59
    _RESOLVING: set = set()                                # line 60
    def find_spec(self, fullname, path, target=None): ...
    # Skips when:
    # - top_submodule in _CORE_SUBMODULES (line 75)
    # After TASK-733: "databasequery" IS in _CORE_SUBMODULES → not hijacked.
```

### Does NOT Exist
- ~~`TOOL_REGISTRY` is mutated at runtime~~ — it's a module-level dict
  literal, edit the source file.
- ~~Need to update `parrot_tools/__init__.py` __all__~~ — `__all__` only
  lists `__version__` and `TOOL_REGISTRY` (verified at line 135). The
  registry edit is sufficient.
- ~~A second registry mirror in ai-parrot~~ — `parrot/tools/registry.py`
  exists but does NOT contain a `database_query` entry; no second edit
  needed. Verify before assuming.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py — diff
-    "database_query": "parrot_tools.databasequery.DatabaseQueryTool",
+    "database_query": "parrot.tools.databasequery.DatabaseQueryTool",
```

### Key Constraints

- Do NOT remove the `parrot_tools.databasequery` shim from TASK-734 — it
  remains the back-compat import path for callers that bypass the
  registry.
- Re-read `parrot/tools/registry.py` to confirm there is no duplicate
  `"database_query"` entry. If one exists, update both consistently.

### References in Codebase

- Spec Section 3 Module 6.
- `packages/ai-parrot-tools/src/parrot_tools/__init__.py` — full
  registry definition.

---

## Acceptance Criteria

- [ ] `grep -n '"database_query"' packages/ai-parrot-tools/src/parrot_tools/__init__.py` shows the value `"parrot.tools.databasequery.DatabaseQueryTool"`.
- [ ] `python -c "from parrot_tools import TOOL_REGISTRY; from parrot._imports import lazy_import; tool_cls = lazy_import(TOOL_REGISTRY['database_query']); print(tool_cls.__module__, tool_cls.__name__)"` prints `parrot.tools.databasequery.tool DatabaseQueryTool`.
- [ ] `python -c "import parrot.tools.databasequery as p; print(p.__file__)"` prints a path inside `packages/ai-parrot/src/parrot/tools/databasequery/__init__.py` (NOT `parrot_tools/databasequery.py`) — confirms the redirector is NOT hijacking.
- [ ] `parrot.tools.registry` (if present) — no duplicate `"database_query"` entry referencing the old path.

---

## Test Specification

TASK-738 adds `test_tool_registry_database_query_path` that exercises the new value end-to-end.

---

## Agent Instructions

1. Confirm TASK-733 and TASK-734 are complete.
2. Apply the one-line registry edit.
3. Run the three smoke commands in acceptance criteria.
4. Move file to `sdd/tasks/completed/`.

---

## Completion Note

## Completion Note

TASK-737 completed successfully.

- Updated parrot_tools/__init__.py:112: database_query registry entry now points to parrot.tools.databasequery.DatabaseQueryTool
- Verified registry value is correct string
- Verified parrot.tools.databasequery is not hijacked by _ParrotToolsRedirector (databasequery is in _CORE_SUBMODULES)
- No second registry mirror in parrot/tools/registry.py (verified)
