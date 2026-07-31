---
type: Wiki Overview
title: 'TASK-1492: Opaque-Source Resolvers'
id: doc:sdd-tasks-completed-task-1492-opaque-source-resolvers-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: with per-type extraction logic for each non-SQL `DataSource` subclass.
relates_to:
- concept: mod:parrot.tools.dataset_manager.sources.airtable
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.deltatable
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.iceberg
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.mongo
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.opaque
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.sources.smartsheet
  rel: mentions
---

# TASK-1492: Opaque-Source Resolvers

**Feature**: FEAT-228 — Deterministic Data-Plane Authorization for DatasetManager
**Spec**: `sdd/specs/dataplane-authz.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec Module 3. Non-SQL sources (Mongo, Iceberg, Delta, Airtable, Smartsheet)
> cannot be parsed with sqlglot. Each needs a per-type strategy to extract a
> resource identifier for policy evaluation. This is a leaf module that provides
> `resolve_opaque_source(source) -> PhysicalResources` called by the main
> resolver (TASK-1491).

---

## Scope

- Implement `resolve_opaque_source(source: DataSource) -> PhysicalResources`
  with per-type extraction logic for each non-SQL `DataSource` subclass.
- Resource identifiers follow the format `source:<type>:<identifier>`:
  - `MongoSource` → `source:mongo:<database>.<collection>`
  - `IcebergSource` → `source:iceberg:<catalog>.<namespace>.<table>`
  - `DeltaTableSource` → `source:delta:<catalog.schema.table or path>`
  - `AirtableSource` → `source:airtable:<base_id>.<table>`
  - `SmartsheetSource` → `source:smartsheet:<sheet_id>`
- Unknown source types return empty `PhysicalResources` (fail-open for
  unrecognized opaque sources).
- Write unit tests for each source type.

**NOT in scope**: SQL parsing (TASK-1491), RLS injection for opaque sources
(TASK-1494), guard evaluation (TASK-1495).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/sources/opaque.py` | CREATE | `resolve_opaque_source()` + per-type extractors |
| `tests/auth/test_opaque_source_resolvers.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Source classes (optional imports — may not be installed)
from parrot.tools.dataset_manager.sources.mongo import MongoSource
# verified: sources/__init__.py:44–50 (conditional import)
# MongoSource.__init__(collection, name, database, credentials, dsn, required_filter)

from parrot.tools.dataset_manager.sources.airtable import AirtableSource
# verified: sources/__init__.py:28
# AirtableSource.__init__(base_id, table, api_key, view)

from parrot.tools.dataset_manager.sources.smartsheet import SmartsheetSource
# verified: sources/__init__.py:29

from parrot.tools.dataset_manager.sources.iceberg import IcebergSource
# verified: sources/__init__.py:36–42 (conditional import)

from parrot.tools.dataset_manager.sources.deltatable import DeltaTableSource
# verified: sources/__init__.py:52–58 (conditional import)
```

### Existing Signatures to Use
```python
# parrot/tools/dataset_manager/sources/mongo.py:70
class MongoSource(DataSource):
    def __init__(self, collection: str, name: str, database: str,
                 credentials=None, dsn=None, required_filter=True):
    # Attrs: self._collection, self._name, self._database

# parrot/tools/dataset_manager/sources/airtable.py:15
class AirtableSource(DataSource):
    def __init__(self, base_id: str, table: str, api_key=None, view=None):
    # Attrs: self._base_id, self._table

# parrot/tools/dataset_manager/sources/smartsheet.py:14
class SmartsheetSource(DataSource):
    # Attrs: self._sheet_id (verify exact attr name before implementing)

# parrot/tools/dataset_manager/sources/iceberg.py:70
class IcebergSource(DataSource):
    # Attrs: verify exact constructor params (catalog, namespace, table)

# parrot/tools/dataset_manager/sources/deltatable.py:76
class DeltaTableSource(DataSource):
    # Attrs: verify exact constructor params (catalog, schema, table or path)
```

### Does NOT Exist
- ~~`parrot.tools.dataset_manager.sources.opaque`~~ — does not exist yet (this task creates it)
- ~~`DataSource.source_type`~~ — not a base-class attribute
- ~~`DataSource.resource_id`~~ — not a base-class attribute

---

## Implementation Notes

### Pattern to Follow
```python
from parrot.tools.dataset_manager.sources.base import DataSource

def resolve_opaque_source(source: DataSource) -> "PhysicalResources":
    """Extract resource identifiers from non-SQL DataSource subclasses."""
    from .resolver import PhysicalResources

    # Use isinstance dispatch per source type.
    # Import each source conditionally to handle missing optional deps.
    try:
        from .mongo import MongoSource
        if isinstance(source, MongoSource):
            return PhysicalResources(
                source_type="mongo",
                source_id=f"{source._database}.{source._collection}",
            )
    except ImportError:
        pass

    # ... repeat for IcebergSource, DeltaTableSource, AirtableSource, SmartsheetSource

    return PhysicalResources()  # unknown opaque source
```

### Key Constraints
- All opaque source imports must be conditional (`try/except ImportError`) since
  Mongo, Iceberg, and Delta are optional dependencies.
- Attribute names on each source class must be verified by reading the actual
  source files before implementing. The contract above lists probable attrs but
  some are marked "verify".
- The `PhysicalResources` model is defined in TASK-1491 (`resolver.py`). Import
  it from there.
- No async needed — extraction is synchronous attribute access.

### References in Codebase
- `parrot/tools/dataset_manager/sources/mongo.py` — MongoSource
- `parrot/tools/dataset_manager/sources/iceberg.py` — IcebergSource
- `parrot/tools/dataset_manager/sources/deltatable.py` — DeltaTableSource
- `parrot/tools/dataset_manager/sources/airtable.py` — AirtableSource
- `parrot/tools/dataset_manager/sources/smartsheet.py` — SmartsheetSource

---

## Acceptance Criteria

- [ ] `resolve_opaque_source(MongoSource(...))` → `PhysicalResources(source_type="mongo", source_id="db.collection")`
- [ ] `resolve_opaque_source(AirtableSource(...))` → `PhysicalResources(source_type="airtable", source_id="base.table")`
- [ ] Unknown source type → empty `PhysicalResources`
- [ ] Missing optional dependency (e.g. Iceberg not installed) → graceful fallback
- [ ] All tests pass: `pytest tests/auth/test_opaque_source_resolvers.py -v`
- [ ] No linting errors: `ruff check parrot/tools/dataset_manager/sources/opaque.py`

---

## Test Specification

```python
# tests/auth/test_opaque_source_resolvers.py
import pytest
from unittest.mock import MagicMock
from parrot.tools.dataset_manager.sources.opaque import resolve_opaque_source


class TestResolveOpaqueSource:
    def test_mongo_source(self):
        from parrot.tools.dataset_manager.sources.mongo import MongoSource
        source = MongoSource(
            collection="transactions", name="test",
            database="finance_db",
        )
        result = resolve_opaque_source(source)
        assert result.source_type == "mongo"
        assert result.source_id == "finance_db.transactions"

    def test_airtable_source(self):
        from parrot.tools.dataset_manager.sources.airtable import AirtableSource
        source = AirtableSource(base_id="appXYZ", table="Contacts")
        result = resolve_opaque_source(source)
        assert result.source_type == "airtable"
        assert result.source_id == "appXYZ.Contacts"

    def test_unknown_source_returns_empty(self):
        source = MagicMock(spec=[])
        result = resolve_opaque_source(source)
        assert result.source_type is None
        assert result.source_id is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/dataplane-authz.spec.md` §5.2b for opaque-source details
2. **Check dependencies** — none; start immediately
3. **Verify the Codebase Contract** — READ each opaque source file to confirm exact attribute names
4. **Update status** in `sdd/tasks/index/dataplane-authz.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1492-opaque-source-resolvers.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-08
**Notes**: AirtableSource uses `self.base_id`/`self.table` (no underscore). SmartsheetSource uses `self.sheet_id`. All 5 tests pass.

**Deviations from spec**: AirtableSource and SmartsheetSource use public (non-underscore) attribute names, not the `_base_id`/`_table`/`_sheet_id` form listed in the contract.
