# TASK-736: `parrot.tools.database` deprecation shim

**Feature**: databasetoolkit-clash
**Spec**: `sdd/specs/databasetoolkit-clash.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-733, TASK-735
**Assigned-to**: unassigned

---

## Context

After TASK-733 the `parrot/tools/database/` directory no longer exists,
and after TASK-735 the public class is `DatabaseQueryToolkit` at
`parrot.tools.databasequery.toolkit`. To keep
`from parrot.tools.database import DatabaseToolkit` working for one
deprecation cycle, add a single-file `parrot/tools/database.py` shim
that re-exports the renamed symbols and emits a `DeprecationWarning`.

Implements **Module 4** of the spec.

---

## Scope

- Create `packages/ai-parrot/src/parrot/tools/database.py` (a `.py` file,
  NOT a package) containing:
  - One-time `warnings.warn(..., DeprecationWarning, stacklevel=2)` on
    import (guarded by a module-level `_warned` flag to avoid noise on
    repeated imports).
  - Re-exports: `DatabaseToolkit = DatabaseQueryToolkit` plus
    `AbstractDatabaseSource`, `ValidationResult`, `ColumnMeta`,
    `TableMeta`, `MetadataResult`, `QueryResult`, `RowResult`.
- Confirm the file is loadable AFTER TASK-733 (which removed the
  `database/` directory). `python -c "import parrot.tools.database"`
  must succeed and resolve to the new shim file.
- Update `parrot/tools/databasequery/__init__.py` to drop the legacy
  `DatabaseToolkit` re-export added back in TASK-735 (the deprecation
  alias now lives only in the shim file at `parrot.tools.database`).

**NOT in scope**:
- Modifying `TOOL_REGISTRY` (TASK-737).
- Touching legacy callers in `parrot/bots/` — none import
  `parrot.tools.database.DatabaseToolkit` today (verified by grep).
- Adding tests (TASK-738).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/database.py` | CREATE | Deprecation shim |
| `packages/ai-parrot/src/parrot/tools/databasequery/__init__.py` | MODIFY | Remove legacy `DatabaseToolkit` re-export (only `DatabaseQueryToolkit` exposed from the new package) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# After TASK-735, the new public surface
from parrot.tools.databasequery import (
    DatabaseQueryToolkit,
    DatabaseQueryTool,
    AbstractDatabaseSource,
    ValidationResult, ColumnMeta, TableMeta,
    MetadataResult, QueryResult, RowResult,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/__init__.py:43-47
_CORE_TOOLS_DIR = _Path(__file__).parent
_CORE_SUBMODULES: frozenset = frozenset(
    {p.stem for p in _CORE_TOOLS_DIR.glob("*.py") if p.stem != "__init__"}
    | {p.name for p in _CORE_TOOLS_DIR.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
)
# After this task: "database" appears in the set via the .py glob, AND
# "databasequery" appears via the directory glob. The redirector skips
# both — neither is hijacked.
```

### Does NOT Exist
- ~~`parrot.tools.database` as both a package directory AND a module file~~
  — Python forbids this. Only safe BECAUSE TASK-733 removed the
  `database/` directory. Verify with
  `ls packages/ai-parrot/src/parrot/tools/ | grep -E "^database"`
  before creating the shim — only `database.py` (the shim) and
  `databasequery/` (the directory) should appear.
- ~~`warnings.warn(..., category=DeprecationWarning, once=True)`~~ —
  there is no `once=` kwarg. Use a module-level `_warned` flag for the
  one-shot behavior.
- ~~Re-exporting `DatabaseQueryTool` from the deprecation shim~~ — the
  legacy tool already has its own compat path
  (`parrot_tools.databasequery.DatabaseQueryTool`); duplicating it from
  `parrot.tools.database` would broaden the deprecation surface
  unnecessarily.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/src/parrot/tools/database.py
"""Deprecated alias — use ``parrot.tools.databasequery`` instead.

Kept for one minor-release cycle to avoid breaking existing imports.
The ``DatabaseToolkit`` name was renamed to ``DatabaseQueryToolkit``
to resolve a clash with ``parrot.bots.database.toolkits.base.DatabaseToolkit``.
"""
from __future__ import annotations

import warnings

from parrot.tools.databasequery import (
    AbstractDatabaseSource,
    ColumnMeta,
    DatabaseQueryToolkit,
    MetadataResult,
    QueryResult,
    RowResult,
    TableMeta,
    ValidationResult,
)

#: Legacy alias — emits DeprecationWarning when this module is imported.
DatabaseToolkit = DatabaseQueryToolkit

_warned = False
if not _warned:
    warnings.warn(
        "parrot.tools.database is deprecated; "
        "import from parrot.tools.databasequery (DatabaseQueryToolkit) instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    _warned = True

__all__ = [
    "DatabaseToolkit",
    "AbstractDatabaseSource",
    "ValidationResult",
    "ColumnMeta",
    "TableMeta",
    "MetadataResult",
    "QueryResult",
    "RowResult",
]
```

### Key Constraints

- The `_warned` guard sits at module level so the warning fires once per
  Python interpreter, not once per import statement (Python caches the
  module after the first import; the assignment is harmless on later
  imports because the module is not re-executed).
- DO NOT raise on import — silent fallback is required for compatibility.
- DO NOT add `cleanup`, `get_source`, or any other shimmed methods —
  `DatabaseToolkit` and `DatabaseQueryToolkit` reference the same class,
  so all methods are reachable via either name.

### References in Codebase

- Spec Section 2 (Component Diagram, "AFTER" block).
- Spec Section 7 Risks — note the `pytest -W error` caveat.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/tools/database.py` exists.
- [ ] `packages/ai-parrot/src/parrot/tools/database/` directory does NOT exist (TASK-733 should have removed it; verify).
- [ ] `python -c "import parrot.tools.database"` emits a `DeprecationWarning` mentioning `parrot.tools.databasequery`.
- [ ] `python -c "from parrot.tools.database import DatabaseToolkit; from parrot.tools.databasequery import DatabaseQueryToolkit; assert DatabaseToolkit is DatabaseQueryToolkit"` succeeds.
- [ ] `python -W error::DeprecationWarning -c "from parrot.tools.databasequery import DatabaseQueryToolkit"` succeeds (the new package itself does NOT emit any warning).
- [ ] `parrot.tools.databasequery.__init__.py` no longer exports `DatabaseToolkit` (only `DatabaseQueryToolkit`).

---

## Test Specification

Tests in TASK-738 will assert the deprecation warning fires and the alias resolves.

---

## Agent Instructions

1. Confirm TASK-733 (rename) and TASK-735 (toolkit refactor) are complete.
2. Verify the `database/` directory is gone before creating `database.py`.
3. Implement the shim, run smoke imports.
4. Move file to `sdd/tasks/completed/`.

---

## Completion Note

## Completion Note

TASK-736 completed successfully.

- Created packages/ai-parrot/src/parrot/tools/database.py (single-file shim, NOT a package directory)
- Emits DeprecationWarning mentioning parrot.tools.databasequery on import
- Re-exports: DatabaseToolkit=DatabaseQueryToolkit, AbstractDatabaseSource, ValidationResult, ColumnMeta, TableMeta, MetadataResult, QueryResult, RowResult
- Verified: our specific DeprecationWarning fires (1 hit with correct message)
- Verified: DatabaseToolkit is DatabaseQueryToolkit (same class)
- Verified: parrot.tools.databasequery does not emit deprecation warning
