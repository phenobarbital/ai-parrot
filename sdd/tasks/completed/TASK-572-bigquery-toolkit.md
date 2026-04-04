# TASK-572: BigQueryToolkit — BigQuery-Specific Overrides

**Feature**: sqlagent-repair
**Spec**: `sdd/specs/sqlagent-repair.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-570
**Assigned-to**: unassigned

---

## Context

Implements spec Module 5. `BigQueryToolkit` overrides `SQLToolkit` for BigQuery: `INFORMATION_SCHEMA.TABLES`/`COLUMNS` syntax, dry-run cost estimation instead of `EXPLAIN ANALYZE`, project/dataset-based connection via `google-cloud-bigquery` or asyncdb bigquery driver. Absorbs `BQSchemaSearchTool` from `parrot_tools/database/bq.py`.

---

## Scope

- Implement `BigQueryToolkit(SQLToolkit)` in `toolkits/bigquery.py`
- Constructor accepts: `project_id`, `dataset`, `credentials_file`, `location` (in addition to base params)
- Override dialect hooks:
  - `_get_explain_prefix()` → BigQuery dry-run cost estimation (no EXPLAIN ANALYZE)
  - `_get_information_schema_query()` → BigQuery `INFORMATION_SCHEMA.TABLES`/`COLUMNS` syntax
  - `_build_dsn()` → BigQuery connection string format
- `start()` → connect via asyncdb bigquery driver or `google-cloud-bigquery` client
- Override `explain_query()` to use BigQuery's `dry_run=True` for cost estimation
- Port logic from `parrot/bots/db/bigquery.py` (BigQueryAgent) and `parrot_tools/database/bq.py` (BQSchemaSearchTool)
- Write unit tests

**NOT in scope**: PostgreSQL, InfluxDB, Elasticsearch, DocumentDB. Agent integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/database/toolkits/bigquery.py` | CREATE | BigQueryToolkit implementation |
| `parrot/bots/database/toolkits/__init__.py` | MODIFY | Add BigQueryToolkit export |
| `tests/unit/test_bigquery_toolkit.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.database.toolkits.sql import SQLToolkit  # TASK-570 output
from parrot.bots.database.models import TableMetadata     # models.py:104
```

### Existing Signatures to Use
```python
# parrot/bots/db/bigquery.py (lines 53-200+) — port from here
# class BigQueryAgent(AbstractDBAgent):
#   project_id: str, credentials_file: str, dataset: str, location: str = "US"
#   client: Optional[bq.Client]
#   async def connect_database(self):  # line 123
#   async def extract_schema_metadata(self):  # line 162

# parrot_tools/database/bq.py:10 — absorb into BigQueryToolkit
# class BQSchemaSearchTool(AbstractSchemaManagerTool): ...
```

### Does NOT Exist
- ~~`BigQueryToolkit`~~ — does not exist yet (this task creates it)
- ~~`SQLToolkit._get_bigquery_client()`~~ — no such method on base
- ~~BigQuery `EXPLAIN ANALYZE`~~ — BigQuery has no EXPLAIN; uses dry-run instead

---

## Implementation Notes

### Key Constraints
- BigQuery uses `project_id` + `dataset` instead of traditional DSN
- BigQuery `INFORMATION_SCHEMA` is per-dataset: `{project}.{dataset}.INFORMATION_SCHEMA.TABLES`
- Cost estimation via `job_config.dry_run = True` replaces `EXPLAIN ANALYZE`
- `google-cloud-bigquery` is an optional dependency — handle ImportError gracefully
- asyncdb bigquery driver name is `'bigquery'`

### References in Codebase
- `parrot/bots/db/bigquery.py` — full BigQueryAgent to port from
- `parrot_tools/database/bq.py` — BQSchemaSearchTool to absorb

---

## Acceptance Criteria

- [ ] `BigQueryToolkit` inherits from `SQLToolkit`
- [ ] `explain_query()` uses dry-run cost estimation
- [ ] Schema introspection uses BigQuery `INFORMATION_SCHEMA` syntax
- [ ] Constructor accepts `project_id`, `dataset`, `credentials_file`
- [ ] All tests pass: `pytest tests/unit/test_bigquery_toolkit.py -v`
- [ ] Imports work: `from parrot.bots.database.toolkits import BigQueryToolkit`

---

## Test Specification

```python
import pytest
from parrot.bots.database.toolkits.bigquery import BigQueryToolkit


class TestBigQueryToolkit:
    def test_inherits_sql_toolkit(self):
        from parrot.bots.database.toolkits.sql import SQLToolkit
        assert issubclass(BigQueryToolkit, SQLToolkit)

    def test_no_explain_analyze(self):
        tk = BigQueryToolkit(
            project_id="test-project", dataset="test_dataset",
            dsn="bigquery://test", backend="asyncdb"
        )
        # BigQuery doesn't use EXPLAIN ANALYZE
        assert "ANALYZE" not in tk._get_explain_prefix()

    def test_constructor_params(self):
        tk = BigQueryToolkit(
            project_id="my-project", dataset="analytics",
            credentials_file="/path/to/creds.json",
            dsn="bigquery://", backend="asyncdb"
        )
        assert tk.project_id == "my-project"
        assert tk.dataset == "analytics"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sqlagent-repair.spec.md` (Module 5)
2. **Check dependencies** — verify TASK-570 is completed
3. **Read `parrot/bots/db/bigquery.py`** and `parrot_tools/database/bq.py` — primary sources to port
4. **Implement** following the scope above
5. **Move this file** to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*
