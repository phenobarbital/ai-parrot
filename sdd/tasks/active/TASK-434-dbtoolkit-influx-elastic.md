# TASK-434: InfluxDB & Elasticsearch Sources

**Feature**: DatabaseToolkit
**Feature ID**: FEAT-062
**Spec**: `sdd/specs/databasetoolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-427, TASK-428
**Assigned-to**: unassigned

---

## Context

InfluxDB and Elasticsearch are non-SQL sources with unique query languages (Flux
and JSON DSL respectively). Both must override `validate_query()` with custom
validation logic and have non-standard metadata discovery.

Implements **Modules 7g, 7h** from the spec.

---

## Scope

### InfluxSource
- Driver `"influx"`, `sqlglot_dialect = None`.
- Override `validate_query()` with Flux syntax validation:
  - Check for `from(bucket:` pattern.
  - Verify balanced pipes and basic Flux structure.
  - Return `ValidationResult` with `dialect="flux"`.
- Implement `get_metadata()`:
  - Return buckets as "tables" (use Flux `buckets()` query).
  - Return field keys as "columns" (use Flux `schema.fieldKeys()` or similar).
- Implement `query()` — accepts Flux query strings.
- Implement `query_row()` — returns first record from Flux result.

### ElasticSource
- Driver `"elastic"`, `sqlglot_dialect = None`.
- Override `validate_query()` with JSON DSL validation:
  - Parse as JSON.
  - Verify it's a dict containing `"query"`, `"aggs"`, `"size"`, or other
    valid Elasticsearch query body keys.
  - Return `ValidationResult` with `dialect="json-dsl"`.
- Implement `get_metadata()`:
  - Return index mappings as tables.
  - Return field properties (type, index, etc.) as columns.
- Implement `query()` — accepts JSON DSL query body string.
- Implement `query_row()` — returns first hit from search results.
- Single source for both Elasticsearch and OpenSearch (asyncdb handles differences).

**NOT in scope**: SQL sources, MongoDB-family sources.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/database/sources/influx.py` | CREATE | InfluxSource |
| `parrot/tools/database/sources/elastic.py` | CREATE | ElasticSource |

---

## Implementation Notes

### InfluxSource Pattern
```python
import re
from parrot.tools.database.base import AbstractDatabaseSource, ValidationResult
from parrot.tools.database.sources import register_source

_FLUX_FROM_PATTERN = re.compile(r'from\s*\(\s*bucket\s*:', re.IGNORECASE)

@register_source("influx")
class InfluxSource(AbstractDatabaseSource):
    driver = "influx"
    sqlglot_dialect = None

    async def validate_query(self, query: str) -> ValidationResult:
        query = query.strip()
        if not query:
            return ValidationResult(valid=False, error="Empty query")
        if not _FLUX_FROM_PATTERN.search(query):
            return ValidationResult(
                valid=False,
                error="Flux query must contain from(bucket:...) clause",
                dialect="flux",
            )
        return ValidationResult(valid=True, dialect="flux")
```

### ElasticSource Pattern
```python
import json
from parrot.tools.database.base import AbstractDatabaseSource, ValidationResult
from parrot.tools.database.sources import register_source

_VALID_ES_KEYS = {"query", "aggs", "aggregations", "size", "from", "sort",
                   "_source", "highlight", "post_filter", "suggest", "script_fields"}

@register_source("elastic")
class ElasticSource(AbstractDatabaseSource):
    driver = "elastic"
    sqlglot_dialect = None

    async def validate_query(self, query: str) -> ValidationResult:
        try:
            parsed = json.loads(query)
            if not isinstance(parsed, dict):
                return ValidationResult(valid=False, error="Query must be a JSON object")
            if not parsed.keys() & _VALID_ES_KEYS:
                return ValidationResult(
                    valid=False,
                    error=f"Query must contain at least one of: {sorted(_VALID_ES_KEYS)}"
                )
            return ValidationResult(valid=True, dialect="json-dsl")
        except json.JSONDecodeError as e:
            return ValidationResult(valid=False, error=str(e))
```

### Key Constraints
- InfluxDB uses Flux only (not InfluxQL) per resolved open question
- Flux validation is lightweight (pattern match) — no full Flux parser available
- Elasticsearch metadata comes from `_mapping` API via asyncdb
- InfluxDB metadata comes from `buckets()` and `schema.fieldKeys()` Flux queries
- asyncdb driver for InfluxDB is `"influx"`, for Elasticsearch is `"elastic"`

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/databasequery.py` —
  `DriverInfo.DRIVER_MAP["influx"]` and `DriverInfo.DRIVER_MAP["elastic"]`

---

## Acceptance Criteria

- [ ] `InfluxSource` registered as `"influx"`
- [ ] Flux query with `from(bucket:...)` validates as `valid=True`
- [ ] Non-Flux query validates as `valid=False`
- [ ] InfluxDB `get_metadata()` returns buckets as tables, field keys as columns
- [ ] `ElasticSource` registered as `"elastic"`
- [ ] Valid JSON DSL with `"query"` key validates as `valid=True`
- [ ] Non-JSON validates as `valid=False`
- [ ] JSON without valid ES keys validates as `valid=False`
- [ ] Elasticsearch `get_metadata()` returns index mappings as tables
- [ ] Both importable from their respective modules

---

## Test Specification

```python
# tests/tools/database/test_influx_elastic.py
import pytest
from parrot.tools.database.sources.influx import InfluxSource
from parrot.tools.database.sources.elastic import ElasticSource


class TestInfluxSource:
    def test_driver_and_dialect(self):
        src = InfluxSource()
        assert src.driver == "influx"
        assert src.sqlglot_dialect is None

    @pytest.mark.asyncio
    async def test_validate_valid_flux(self):
        src = InfluxSource()
        result = await src.validate_query(
            'from(bucket: "my-bucket") |> range(start: -1h) |> filter(fn: (r) => r._measurement == "cpu")'
        )
        assert result.valid is True
        assert result.dialect == "flux"

    @pytest.mark.asyncio
    async def test_validate_invalid_flux(self):
        src = InfluxSource()
        result = await src.validate_query("SELECT * FROM cpu")
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_validate_empty(self):
        src = InfluxSource()
        result = await src.validate_query("")
        assert result.valid is False


class TestElasticSource:
    def test_driver_and_dialect(self):
        src = ElasticSource()
        assert src.driver == "elastic"
        assert src.sqlglot_dialect is None

    @pytest.mark.asyncio
    async def test_validate_valid_query(self):
        src = ElasticSource()
        result = await src.validate_query('{"query": {"match_all": {}}}')
        assert result.valid is True
        assert result.dialect == "json-dsl"

    @pytest.mark.asyncio
    async def test_validate_valid_aggs(self):
        src = ElasticSource()
        result = await src.validate_query('{"aggs": {"avg_price": {"avg": {"field": "price"}}}}')
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_invalid_json(self):
        src = ElasticSource()
        result = await src.validate_query("not json")
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_validate_no_valid_keys(self):
        src = ElasticSource()
        result = await src.validate_query('{"invalid_key": 123}')
        assert result.valid is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/databasetoolkit.spec.md` for full context
2. **Check dependencies** — TASK-427 and TASK-428 must be completed
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-434-dbtoolkit-influx-elastic.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
