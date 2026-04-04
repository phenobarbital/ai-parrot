# TASK-573: InfluxDBToolkit — InfluxDB Flux Query Support

**Feature**: sqlagent-repair
**Spec**: `sdd/specs/sqlagent-repair.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-569
**Assigned-to**: unassigned

---

## Context

Implements spec Module 6. `InfluxDBToolkit` inherits directly from `DatabaseToolkit` (not `SQLToolkit`) because InfluxDB uses Flux query language, not SQL. Port from `parrot/bots/db/influx.py:InfluxDBAgent`.

---

## Scope

- Implement `InfluxDBToolkit(DatabaseToolkit)` in `toolkits/influx.py`
- Constructor accepts: `connection_string`, `token`, `org`, `bucket`, `default_time_range`
- LLM-callable tools (async methods):
  - `search_measurements(search_term, limit)` — discover measurements in bucket
  - `generate_flux_query(natural_language, measurement)` — generate Flux query from description
  - `execute_flux_query(query, limit, timeout)` → `QueryExecutionResponse`
  - `explore_buckets()` — list available buckets
- `start()` → connect via asyncdb influx driver
- `stop()` → close connection
- Port measurement metadata extraction from `parrot/bots/db/influx.py`
- Write unit tests

**NOT in scope**: SQL databases, agent integration, Flux query generation by LLM (that's the agent's job via tool calling).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/database/toolkits/influx.py` | CREATE | InfluxDBToolkit implementation |
| `parrot/bots/database/toolkits/__init__.py` | MODIFY | Add InfluxDBToolkit export |
| `tests/unit/test_influxdb_toolkit.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.database.toolkits.base import DatabaseToolkit  # TASK-569 output
from parrot.bots.database.models import QueryExecutionResponse  # models.py:180
from asyncdb import AsyncDB  # external
```

### Existing Signatures to Use
```python
# parrot/bots/db/influx.py (lines 54-190+) — port from here
# class InfluxDBAgent(AbstractDBAgent):
#   connection_string: str, token: str, org: str, bucket: str
#   max_sample_records: int = 10, default_time_range: str = "-30d"
#   client: Optional[InfluxDBClientAsync]
#   measurements_cache: Dict[str, InfluxMeasurementMetadata]
```

### Does NOT Exist
- ~~`InfluxDBToolkit`~~ — does not exist yet (this task creates it)
- ~~`DatabaseToolkit.generate_flux_query()`~~ — not on base class; InfluxDB-specific
- ~~`InfluxMeasurementMetadata` in models.py~~ — only exists in `bots/db/influx.py`, may need to be added to models or defined locally

---

## Implementation Notes

### Key Constraints
- InfluxDB uses Flux language, not SQL — completely different query syntax
- asyncdb influx driver name is `'influx'`
- Time-series data always has a time dimension; `default_time_range` filters by default
- Measurement metadata is analogous to table metadata but with fields/tags instead of columns

### References in Codebase
- `parrot/bots/db/influx.py` — full InfluxDBAgent to port from

---

## Acceptance Criteria

- [ ] `InfluxDBToolkit` inherits from `DatabaseToolkit` (NOT `SQLToolkit`)
- [ ] `search_measurements()`, `execute_flux_query()`, `explore_buckets()` are LLM-callable tools
- [ ] Constructor accepts InfluxDB-specific params (token, org, bucket)
- [ ] All tests pass: `pytest tests/unit/test_influxdb_toolkit.py -v`
- [ ] Imports work: `from parrot.bots.database.toolkits import InfluxDBToolkit`

---

## Test Specification

```python
import pytest
from parrot.bots.database.toolkits.influx import InfluxDBToolkit
from parrot.bots.database.toolkits.base import DatabaseToolkit
from parrot.bots.database.toolkits.sql import SQLToolkit


class TestInfluxDBToolkit:
    def test_inherits_database_toolkit(self):
        assert issubclass(InfluxDBToolkit, DatabaseToolkit)

    def test_not_sql_toolkit(self):
        assert not issubclass(InfluxDBToolkit, SQLToolkit)

    def test_tool_methods(self):
        tk = InfluxDBToolkit(
            dsn="http://localhost:8086", token="test-token",
            org="test-org", bucket="test-bucket", backend="asyncdb"
        )
        tool_names = [t.name for t in tk.get_tools()]
        assert "search_measurements" in tool_names
        assert "execute_flux_query" in tool_names
        assert "explore_buckets" in tool_names
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sqlagent-repair.spec.md` (Module 6)
2. **Check dependencies** — verify TASK-569 is completed
3. **Read `parrot/bots/db/influx.py`** — primary source to port from
4. **Implement** following the scope above
5. **Move this file** to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*
