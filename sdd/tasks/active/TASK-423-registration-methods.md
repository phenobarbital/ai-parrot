# TASK-423: DatasetManager Registration Methods + DatasetInfo Update

**Feature**: datasetmanager-sources
**Spec**: `sdd/specs/datasetmanager-sources.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-420, TASK-421, TASK-422
**Assigned-to**: unassigned

---

## Context

> This task implements Module 4 from the spec: the registration methods on `DatasetManager`
> and the `DatasetInfo` source_type update. It depends on all three source implementations
> being complete first, as it imports and instantiates them.

---

## Scope

- Add `add_iceberg_source()` async registration method to `DatasetManager`:
  - Creates `IcebergSource`, calls `prefetch_schema()`, creates `DatasetEntry`, registers
  - Parameters: `name, table_id, catalog_params, description, metadata, cache_ttl, factory, is_active`
  - Returns confirmation string with schema column count
- Add `create_iceberg_from_dataframe()` async method:
  - Calls `IcebergSource.create_table_from_df()` to write DataFrame to Iceberg
  - Then registers the new Iceberg table as a source via `add_iceberg_source()`
  - Parameters: `name, df, table_id, namespace, catalog_params, description, mode`
- Add `add_mongo_source()` async registration method:
  - Creates `MongoSource`, calls `prefetch_schema()`, creates `DatasetEntry`, registers
  - Parameters: `name, collection, database, dsn, credentials, description, metadata, cache_ttl, is_active`
  - Returns confirmation string
- Add `add_deltatable_source()` async registration method:
  - Creates `DeltaTableSource`, calls `prefetch_schema()`, creates `DatasetEntry`, registers
  - Parameters: `name, path, table_name, mode, description, metadata, cache_ttl, is_active`
  - Returns confirmation string with schema column count
- Add `create_deltatable_from_parquet()` async method:
  - Calls `DeltaTableSource.create_from_parquet()` to create Delta table from Parquet
  - Then registers the new Delta table as a source via `add_deltatable_source()`
  - Parameters: `name, parquet_path, delta_path, table_name, mode, description`
- Update `DatasetInfo.source_type` Literal to include `"iceberg"`, `"mongo"`, `"deltatable"`
- Update `_generate_dataframe_guide()` to render new source types:
  - Iceberg: show SQL hint with table_id
  - Mongo: show filter+projection requirement
  - Delta: show SQL/filter/column query options
- Write unit tests for all registration methods and guide rendering

**NOT in scope**: Source implementations (TASK-420/421/422), exports (TASK-424)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | Add registration methods, update DatasetInfo, update guide |
| `packages/ai-parrot/tests/tools/test_dataset_new_registration.py` | CREATE | Unit tests for registration methods |

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the same pattern as add_table_source() and add_airtable_source():
async def add_iceberg_source(
    self,
    name: str,
    table_id: str,
    *,
    catalog_params: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    cache_ttl: int = 3600,
    factory: str = "pandas",
    is_active: bool = True,
) -> str:
    if not catalog_params:
        raise ValueError("catalog_params is required for IcebergSource")
    source = IcebergSource(
        table_id=table_id,
        name=name,
        catalog_params=catalog_params,
        factory=factory,
    )
    schema = await source.prefetch_schema()
    entry = DatasetEntry(
        name=name,
        source=source,
        description=description,
        metadata=metadata or {},
        is_active=is_active,
        cache_ttl=cache_ttl,
    )
    if schema:
        entry._column_types = schema
    self._datasets[name] = entry
    return f"Iceberg source '{name}' registered ({len(schema)} columns)"
```

### Key Constraints
- `catalog_params` is required for Iceberg (raise ValueError if None)
- `filter` and `projection` requirements for Mongo should be documented in the guide
- Follow the `description` parameter pattern from FEAT-059
- Update the `source_type` Literal in `DatasetInfo` — add to the existing list
- Guide rendering should include appropriate usage hints per source type

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — existing registration methods
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/` — source implementations

---

## Acceptance Criteria

- [ ] `add_iceberg_source()` registers IcebergSource with prefetched schema
- [ ] `create_iceberg_from_dataframe()` creates Iceberg table + registers source
- [ ] `add_mongo_source()` registers MongoSource with prefetched schema
- [ ] `add_deltatable_source()` registers DeltaTableSource with prefetched schema
- [ ] `create_deltatable_from_parquet()` creates Delta table + registers source
- [ ] `DatasetInfo.source_type` includes `iceberg`, `mongo`, `deltatable`
- [ ] LLM guide renders Iceberg with SQL hint
- [ ] LLM guide renders Mongo with filter+projection requirement
- [ ] LLM guide renders Delta with query options
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_dataset_new_registration.py -v`

---

## Test Specification

```python
import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch, MagicMock


class TestIcebergRegistration:
    async def test_add_iceberg_source(self):
        """add_iceberg_source registers entry with prefetched schema."""
        ...

    async def test_add_iceberg_source_no_catalog_raises(self):
        """add_iceberg_source raises ValueError without catalog_params."""
        ...

    async def test_create_iceberg_from_df(self):
        """create_iceberg_from_dataframe creates table + registers source."""
        ...


class TestMongoRegistration:
    async def test_add_mongo_source(self):
        """add_mongo_source registers entry with prefetched schema."""
        ...


class TestDeltaRegistration:
    async def test_add_deltatable_source(self):
        """add_deltatable_source registers entry with prefetched schema."""
        ...

    async def test_create_deltatable_from_parquet(self):
        """create_deltatable_from_parquet creates delta + registers source."""
        ...


class TestDatasetInfoSourceTypes:
    def test_new_source_types_accepted(self):
        """DatasetInfo.source_type accepts iceberg, mongo, deltatable."""
        ...


class TestGuideRendering:
    def test_guide_iceberg_source(self):
        """Guide renders Iceberg source with SQL hint."""
        ...

    def test_guide_mongo_source(self):
        """Guide renders Mongo source with filter requirement."""
        ...

    def test_guide_deltatable_source(self):
        """Guide renders Delta source with query options."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-sources.spec.md` for full context
2. **Check dependencies** — verify TASK-420, TASK-421, TASK-422 are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-423-registration-methods.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
