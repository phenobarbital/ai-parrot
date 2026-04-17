# TASK-733: Rename package `parrot.tools.database` → `parrot.tools.databasequery`

**Feature**: databasetoolkit-clash
**Spec**: `sdd/specs/databasetoolkit-clash.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The new multi-database toolkit from FEAT-062 currently lives at
`packages/ai-parrot/src/parrot/tools/database/` and exports a class named
`DatabaseToolkit`. The same class name exists in
`packages/ai-parrot/src/parrot/bots/database/toolkits/base.py` (used by
`SQLAgent`) — a cosmetic clash that confuses imports and docstrings.

This task is the **mechanical rename** that the rest of FEAT-105 builds on:
move the folder, update every intra-package import, and update the
registry's source-module path list. No behavior change, no toolkit rewrite
here — that is TASK-735.

Implements **Module 1** of the spec.

---

## Scope

- `git mv packages/ai-parrot/src/parrot/tools/database packages/ai-parrot/src/parrot/tools/databasequery` to preserve history.
- Update every import inside the moved package that referenced
  `parrot.tools.database.*` to `parrot.tools.databasequery.*`. Files:
  - `databasequery/__init__.py` (was `database/__init__.py`)
  - `databasequery/toolkit.py`
  - `databasequery/base.py` (no intra-package imports today, confirm)
  - `databasequery/sources/__init__.py` — **critical**: the
    `_source_modules` list at line 106 contains 13 hardcoded
    `"parrot.tools.database.sources.<name>"` strings that MUST be renamed.
  - `databasequery/sources/atlas.py`, `documentdb.py`, plus every other source file whose `from parrot.tools.database.sources...` imports are listed in the Codebase Contract below.
- Do NOT yet create a `parrot/tools/database.py` shim (TASK-736).
- Do NOT yet update `TOOL_REGISTRY` (TASK-737).
- Do NOT yet move `parrot_tools/databasequery.py` (TASK-734).
- Do NOT touch `parrot/bots/database/**` — unchanged.

**NOT in scope**:
- Renaming the class `DatabaseToolkit` → `DatabaseQueryToolkit` (TASK-735 does that inside the moved `toolkit.py`).
- Updating test files (TASK-738).
- Adding `QueryValidator` safety (TASK-735).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/database/` | MOVE | `git mv` → `packages/ai-parrot/src/parrot/tools/databasequery/` |
| `.../databasequery/__init__.py` | MODIFY | Update internal imports `database` → `databasequery` |
| `.../databasequery/toolkit.py` | MODIFY | Update internal imports (class renames come in TASK-735) |
| `.../databasequery/sources/__init__.py` | MODIFY | Rename all 13 strings in `_source_modules` list |
| `.../databasequery/sources/atlas.py` | MODIFY | `from parrot.tools.database.sources...` → `...databasequery.sources...` |
| `.../databasequery/sources/documentdb.py` | MODIFY | Same |
| (other sources/*.py) | CHECK | `grep` for `parrot.tools.database.` — update each if present |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (current paths — will be renamed)
```python
# packages/ai-parrot/src/parrot/tools/database/__init__.py:17
from parrot.tools.database.base import (
    AbstractDatabaseSource, ColumnMeta, MetadataResult, QueryResult,
    RowResult, TableMeta, ValidationResult,
)
# packages/ai-parrot/src/parrot/tools/database/__init__.py:26
from parrot.tools.database.toolkit import DatabaseToolkit

# packages/ai-parrot/src/parrot/tools/database/toolkit.py:24
from parrot.tools.database.base import (
    AbstractDatabaseSource, MetadataResult, QueryResult,
    RowResult, ValidationResult,
)
# packages/ai-parrot/src/parrot/tools/database/toolkit.py:31
from parrot.tools.database.sources import get_source_class, normalize_driver

# packages/ai-parrot/src/parrot/tools/database/sources/atlas.py:12-13
from parrot.tools.database.sources import register_source
from parrot.tools.database.sources.mongodb import MongoSource

# packages/ai-parrot/src/parrot/tools/database/sources/documentdb.py:13-14
from parrot.tools.database.sources import register_source
from parrot.tools.database.sources.mongodb import MongoSource
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/database/sources/__init__.py:106-120
# Hardcoded module paths — MUST be renamed by this task:
_source_modules = [
    "parrot.tools.database.sources.postgres",
    "parrot.tools.database.sources.mysql",
    "parrot.tools.database.sources.sqlite",
    "parrot.tools.database.sources.bigquery",
    "parrot.tools.database.sources.oracle",
    "parrot.tools.database.sources.clickhouse",
    "parrot.tools.database.sources.duckdb",
    "parrot.tools.database.sources.mssql",
    "parrot.tools.database.sources.mongodb",
    "parrot.tools.database.sources.documentdb",
    "parrot.tools.database.sources.atlas",
    "parrot.tools.database.sources.influx",
    "parrot.tools.database.sources.elastic",
]
```

### Does NOT Exist
- ~~`parrot.tools.database.pg` / `parrot.tools.database.bq`~~ — referenced
  dead by `parrot/bots/database/abstract.py:45-46` (`PgSchemaSearchTool`,
  `BQSchemaSearchTool`) — those imports will still fail after the rename
  but they were already failing before; **out of scope** for this task.
  Note: `parrot_tools/database/__init__.py` already declares these classes
  were absorbed into `parrot.bots.database.toolkits.{postgres,bigquery}` in
  FEAT-082, so the stale `bots/database/abstract.py` imports are separate
  pre-existing dead code.
- ~~`parrot.tools.database` top-level re-export in `parrot/tools/__init__.py`~~
  — none exists; the only entry point is through the directory package.
- ~~Renaming `parrot.bots.database.*`~~ — NOT touched by this task (or by this feature).

---

## Implementation Notes

### Pattern to Follow

```bash
# 1. Perform the move (preserves git history)
git mv packages/ai-parrot/src/parrot/tools/database \
       packages/ai-parrot/src/parrot/tools/databasequery

# 2. Sweep internal imports
grep -rln "parrot\.tools\.database\b" \
    packages/ai-parrot/src/parrot/tools/databasequery/ | \
    xargs sed -i 's|parrot\.tools\.database\b|parrot.tools.databasequery|g'

# 3. Verify the _source_modules list was rewritten
grep "_source_modules" -A 15 packages/ai-parrot/src/parrot/tools/databasequery/sources/__init__.py

# 4. Sanity: import must succeed
python -c "from parrot.tools.databasequery import DatabaseToolkit; print(DatabaseToolkit)"
# (DatabaseToolkit still exists here pre-TASK-735; that's fine.)
```

### Key Constraints

- DO NOT use `grep -l ... | xargs sed` without first reviewing the files —
  the repo may have `from parrot.tools.database.*` inside the moved
  package where the `.` boundary matters. Using `\b` in the pattern is
  critical (don't match `databasequery` already).
- DO NOT change any file outside
  `packages/ai-parrot/src/parrot/tools/databasequery/` in this task.
- DO NOT rename the class `DatabaseToolkit` yet. TASK-735 owns that.

### References in Codebase

- Spec Section 3 Module 1 — canonical description.
- `packages/ai-parrot/src/parrot/tools/__init__.py:44` — `_CORE_SUBMODULES`
  is rebuilt from a directory glob at import time, so the rename
  automatically adds `"databasequery"` to the core set.

---

## Acceptance Criteria

- [ ] Directory `packages/ai-parrot/src/parrot/tools/database/` no longer
      exists.
- [ ] Directory `packages/ai-parrot/src/parrot/tools/databasequery/`
      contains `__init__.py`, `base.py`, `toolkit.py`, `sources/`.
- [ ] `grep -rn "parrot\.tools\.database\b" packages/ai-parrot/src/parrot/tools/databasequery/` returns zero matches.
- [ ] `python -c "from parrot.tools.databasequery import DatabaseToolkit"` succeeds.
- [ ] `python -c "from parrot.tools.databasequery.sources import get_source_class, normalize_driver; get_source_class('pg')"` resolves the PostgresSource class (proves `_source_modules` list was updated correctly).
- [ ] `git log --follow packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py` shows history from the old `database/toolkit.py` path (confirms `git mv` was used).

---

## Test Specification

No new tests in this task. Run smoke imports manually per the acceptance
criteria. The test suite updates land in TASK-738.

---

## Agent Instructions

1. Read spec Module 1.
2. Perform `git mv`, then the sed sweep.
3. Run the three acceptance smoke imports manually.
4. Move file to `sdd/tasks/completed/`.

---

## Completion Note

## Completion Note

TASK-733 completed successfully.

- Performed git mv packages/ai-parrot/src/parrot/tools/database → databasequery
- Updated all 16 intra-package files replacing parrot.tools.database with parrot.tools.databasequery
- Updated _source_modules list (all 13 entries) in sources/__init__.py
- Smoke verified: from parrot.tools.databasequery import DatabaseToolkit succeeds
- Smoke verified: get_source_class('pg') resolves PostgresSource correctly
- History preserved via git mv (verified with git log --follow)
