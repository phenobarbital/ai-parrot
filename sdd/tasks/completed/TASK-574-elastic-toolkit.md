# TASK-574: ElasticToolkit — Elasticsearch DSL Support

**Feature**: sqlagent-repair
**Spec**: `sdd/specs/sqlagent-repair.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-569
**Assigned-to**: unassigned

---

## Context

Implements spec Module 7. `ElasticToolkit` inherits from `DatabaseToolkit` (not `SQLToolkit`) because Elasticsearch uses Query DSL, not SQL. Port from `parrot/bots/db/elastic.py:ElasticDbAgent`.

---

## Scope

- Implement `ElasticToolkit(DatabaseToolkit)` in `toolkits/elastic.py`
- Constructor accepts: `connection_string`, `username`, `password`, `api_key`, `cloud_id`, `verify_certs`
- LLM-callable tools:
  - `search_indices(search_term, limit)` — discover indices matching pattern
  - `generate_dsl_query(natural_language, index)` — generate Elasticsearch DSL from description
  - `execute_query(query_dsl, index, size, timeout)` → `QueryExecutionResponse`
  - `run_aggregation(aggregation_dsl, index)` → aggregation results
- `start()` → connect via asyncdb elasticsearch driver
- Port index metadata extraction from `parrot/bots/db/elastic.py`
- Write unit tests

**NOT in scope**: SQL databases, agent integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/database/toolkits/elastic.py` | CREATE | ElasticToolkit implementation |
| `parrot/bots/database/toolkits/__init__.py` | MODIFY | Add ElasticToolkit export |
| `tests/unit/test_elastic_toolkit.py` | CREATE | Unit tests |

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
# parrot/bots/db/elastic.py (lines 54-150+) — port from here
# class ElasticDbAgent(AbstractDBAgent):
#   connection_string: str, username: str, password: str
#   api_key: str, cloud_id: str, verify_certs: bool = True
#   client: Optional[AsyncElasticsearch]
#   indices_cache: Dict[str, IndexMetadata]
```

### Does NOT Exist
- ~~`ElasticToolkit`~~ — does not exist yet (this task creates it)
- ~~`IndexMetadata` in models.py~~ — only in `bots/db/elastic.py`; define locally or add to models

---

## Acceptance Criteria

- [ ] `ElasticToolkit` inherits from `DatabaseToolkit` (NOT `SQLToolkit`)
- [ ] `search_indices()`, `execute_query()`, `run_aggregation()` are LLM-callable tools
- [ ] All tests pass: `pytest tests/unit/test_elastic_toolkit.py -v`
- [ ] Imports work: `from parrot.bots.database.toolkits import ElasticToolkit`

---

## Test Specification

```python
import pytest
from parrot.bots.database.toolkits.elastic import ElasticToolkit
from parrot.bots.database.toolkits.base import DatabaseToolkit


class TestElasticToolkit:
    def test_inherits_database_toolkit(self):
        assert issubclass(ElasticToolkit, DatabaseToolkit)

    def test_tool_methods(self):
        tk = ElasticToolkit(
            dsn="http://localhost:9200", backend="asyncdb"
        )
        tool_names = [t.name for t in tk.get_tools()]
        assert "search_indices" in tool_names
        assert "execute_query" in tool_names
        assert "run_aggregation" in tool_names
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — verify TASK-569 is completed
2. **Read `parrot/bots/db/elastic.py`** — primary source to port from
3. **Implement**, test, move to completed, update index

---

## Completion Note

*(Agent fills this in when done)*
