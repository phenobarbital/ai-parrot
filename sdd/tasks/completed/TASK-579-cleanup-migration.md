# TASK-579: Cleanup & Migration — Delete Old Code, Update Exports

**Feature**: sqlagent-repair
**Spec**: `sdd/specs/sqlagent-repair.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-578
**Assigned-to**: unassigned

---

## Context

Implements spec Module 12. Final cleanup task: update `parrot/bots/database/__init__.py` to export the new `DatabaseAgent` and all toolkits, delete the old `parrot/bots/db/` directory entirely, delete absorbed tools from `parrot_tools/database/` (`pg.py`, `bq.py`), and ensure no remaining imports reference deleted code.

---

## Scope

- Update `parrot/bots/database/__init__.py`:
  - Export `DatabaseAgent` (from `agent.py`)
  - Export all toolkit classes: `DatabaseToolkit`, `SQLToolkit`, `PostgresToolkit`, `BigQueryToolkit`, `InfluxDBToolkit`, `ElasticToolkit`, `DocumentDBToolkit`
  - Export `CacheManager`, `CachePartition`, `CachePartitionConfig`
  - Keep existing model exports
  - Remove old `AbstractDBAgent` and `SQLAgent` exports (or alias for transition if needed)
- Delete `parrot/bots/db/` directory entirely (12 files, 6,386 lines)
- Delete `parrot_tools/database/pg.py` (absorbed into PostgresToolkit)
- Delete `parrot_tools/database/bq.py` (absorbed into BigQueryToolkit)
- Update `parrot_tools/database/__init__.py` to remove deleted exports
- Search for and fix any remaining imports of deleted modules across the codebase
- Verify no test files reference deleted modules
- Run full test suite to confirm no breakage

**NOT in scope**: Adding new features, modifying toolkit implementations.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/database/__init__.py` | MODIFY | Update exports |
| `parrot/bots/db/` | DELETE | Entire directory (12 files) |
| `parrot_tools/database/pg.py` | DELETE | Absorbed into PostgresToolkit |
| `parrot_tools/database/bq.py` | DELETE | Absorbed into BigQueryToolkit |
| `parrot_tools/database/__init__.py` | MODIFY | Remove deleted exports |
| Various | MODIFY | Fix any broken imports found via grep |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Current exports to REMOVE from parrot/bots/database/__init__.py:
from .abstract import AbstractDBAgent  # __init__.py:1 — REMOVE
from .sql import SQLAgent              # __init__.py:2 — REMOVE

# New exports to ADD:
from .agent import DatabaseAgent
from .toolkits import (
    DatabaseToolkit, SQLToolkit, PostgresToolkit,
    BigQueryToolkit, InfluxDBToolkit, ElasticToolkit, DocumentDBToolkit
)
from .cache import CacheManager, CachePartition, CachePartitionConfig
```

### Files to Delete
```
parrot/bots/db/__init__.py
parrot/bots/db/abstract.py
parrot/bots/db/bigquery.py
parrot/bots/db/cache.py
parrot/bots/db/documentdb.py
parrot/bots/db/elastic.py
parrot/bots/db/influx.py
parrot/bots/db/mock.py
parrot/bots/db/multi.py
parrot/bots/db/prompts.py
parrot/bots/db/sql.py
parrot/bots/db/tools.py
parrot_tools/database/pg.py
parrot_tools/database/bq.py
```

### Does NOT Exist
- ~~Consumers of `parrot.bots.db`~~ — confirmed no external consumers (clean break)

---

## Implementation Notes

### Key Constraints
- Before deleting, grep the entire codebase for imports from deleted modules:
  ```
  grep -r "from parrot.bots.db" packages/
  grep -r "from parrot_tools.database.pg import" packages/
  grep -r "from parrot_tools.database.bq import" packages/
  ```
- If any imports are found, fix them to point to new locations
- The old `abstract.py` (3,071 lines) should be kept temporarily if `DatabaseAgent` still references it — but ideally it's fully replaced by TASK-578
- Run `pytest` after deletion to catch any missed references

### References in Codebase
- `parrot/bots/db/__init__.py` — current exports to verify no one imports them
- `parrot_tools/database/__init__.py` — needs update after pg.py/bq.py removal

---

## Acceptance Criteria

- [ ] `parrot/bots/db/` directory is deleted
- [ ] `parrot_tools/database/pg.py` and `bq.py` are deleted
- [ ] `parrot/bots/database/__init__.py` exports `DatabaseAgent` and all toolkits
- [ ] No remaining imports reference `parrot.bots.db` anywhere in codebase
- [ ] No remaining imports reference `parrot_tools.database.pg` or `.bq`
- [ ] `pytest` runs without import errors from deleted modules
- [ ] `from parrot.bots.database import DatabaseAgent` works

---

## Test Specification

```python
# Simple import verification tests
def test_new_exports():
    from parrot.bots.database import DatabaseAgent
    from parrot.bots.database import CacheManager
    from parrot.bots.database.toolkits import (
        DatabaseToolkit, SQLToolkit, PostgresToolkit
    )
    assert DatabaseAgent is not None
    assert CacheManager is not None

def test_old_imports_removed():
    """Old modules should not be importable."""
    import importlib
    with pytest.raises(ImportError):
        importlib.import_module("parrot.bots.db")
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — TASK-578 MUST be completed (DatabaseAgent exists and works)
2. **Grep for all imports** from modules being deleted BEFORE deleting anything
3. **Fix broken imports first**, then delete
4. **Run full test suite** after deletion
5. **Move this file** to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*
