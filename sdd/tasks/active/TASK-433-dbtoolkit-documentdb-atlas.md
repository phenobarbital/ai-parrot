# TASK-433: DocumentDB & Atlas Sources

**Feature**: DatabaseToolkit
**Feature ID**: FEAT-062
**Spec**: `sdd/specs/databasetoolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-427, TASK-428, TASK-432
**Assigned-to**: unassigned

---

## Context

Both DocumentDB and Atlas are MongoDB-compatible databases that reuse `MongoSource`
for query validation, metadata discovery, and execution. They differ only in
credential resolution and asyncdb `dbtype` parameter.

Implements **Modules 7e, 7f** from the spec.

---

## Scope

- Implement `DocumentDBSource` extending `MongoSource`:
  - Registered as `"documentdb"`, asyncdb driver `"mongo"` with `dbtype="documentdb"`.
  - `get_default_credentials()` adds `ssl=True` and default `tlsCAFile` path.
- Implement `AtlasSource` extending `MongoSource`:
  - Registered as `"atlas"`, asyncdb driver `"mongo"` with `dbtype="atlas"`.
  - `get_default_credentials()` uses `mongodb+srv://` connection string format.
- Both inherit `validate_query()`, `get_metadata()`, `query()`, `query_row()`
  from `MongoSource` without override.

**NOT in scope**: Base MongoDB functionality (TASK-432), other sources.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/database/sources/documentdb.py` | CREATE | DocumentDBSource |
| `parrot/tools/database/sources/atlas.py` | CREATE | AtlasSource |

---

## Implementation Notes

### Pattern to Follow
```python
# sources/documentdb.py
from parrot.tools.database.sources.mongodb import MongoSource
from parrot.tools.database.sources import register_source


@register_source("documentdb")
class DocumentDBSource(MongoSource):
    driver = "documentdb"
    dbtype = "documentdb"

    async def get_default_credentials(self) -> dict[str, Any]:
        from parrot.interfaces.database import get_default_credentials
        base = get_default_credentials("documentdb") or {}
        # Ensure SSL defaults for DocumentDB
        if isinstance(base, str):
            base = {"dsn": base}
        base.setdefault("ssl", True)
        base.setdefault("tlsCAFile", "/etc/ssl/certs/global-bundle.pem")
        return base
```

### Key Constraints
- Must import `MongoSource` from `parrot.tools.database.sources.mongodb`
- The `dbtype` attribute is passed to asyncdb when creating the connection
- DocumentDB requires SSL by default (AWS requirement)
- Atlas uses `mongodb+srv://` URI format
- Both must be registered under their own canonical driver names

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/databasequery.py` —
  `DriverInfo.DRIVER_MAP["documentdb"]` and `DriverInfo.DRIVER_MAP["atlas"]`

---

## Acceptance Criteria

- [ ] `DocumentDBSource` registered as `"documentdb"`
- [ ] `DocumentDBSource` extends `MongoSource`
- [ ] `DocumentDBSource.get_default_credentials()` includes `ssl=True`
- [ ] `AtlasSource` registered as `"atlas"`
- [ ] `AtlasSource` extends `MongoSource`
- [ ] Both inherit `validate_query()` from `MongoSource` (JSON validation)
- [ ] Both inherit `get_metadata()`, `query()`, `query_row()` from `MongoSource`
- [ ] Import works: `from parrot.tools.database.sources.documentdb import DocumentDBSource`
- [ ] Import works: `from parrot.tools.database.sources.atlas import AtlasSource`

---

## Test Specification

```python
# tests/tools/database/test_documentdb_atlas.py
import pytest
from parrot.tools.database.sources.documentdb import DocumentDBSource
from parrot.tools.database.sources.atlas import AtlasSource
from parrot.tools.database.sources.mongodb import MongoSource


class TestDocumentDBSource:
    def test_extends_mongo(self):
        assert issubclass(DocumentDBSource, MongoSource)

    def test_driver(self):
        src = DocumentDBSource()
        assert src.driver == "documentdb"

    @pytest.mark.asyncio
    async def test_validate_inherits_json(self):
        src = DocumentDBSource()
        result = await src.validate_query('{"status": "active"}')
        assert result.valid is True


class TestAtlasSource:
    def test_extends_mongo(self):
        assert issubclass(AtlasSource, MongoSource)

    def test_driver(self):
        src = AtlasSource()
        assert src.driver == "atlas"

    @pytest.mark.asyncio
    async def test_validate_inherits_json(self):
        src = AtlasSource()
        result = await src.validate_query('{"status": "active"}')
        assert result.valid is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/databasetoolkit.spec.md` for full context
2. **Check dependencies** — TASK-427, TASK-428, and TASK-432 must be completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-433-dbtoolkit-documentdb-atlas.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
