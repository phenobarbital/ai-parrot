# TASK-575: DocumentDBToolkit — MongoDB Query Language Support

**Feature**: sqlagent-repair
**Spec**: `sdd/specs/sqlagent-repair.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-569
**Assigned-to**: unassigned

---

## Context

Implements spec Module 8. `DocumentDBToolkit` inherits from `DatabaseToolkit` for AWS DocumentDB (MongoDB-compatible). Port from `parrot/bots/db/documentdb.py:DocumentDBAgent`.

---

## Scope

- Implement `DocumentDBToolkit(DatabaseToolkit)` in `toolkits/documentdb.py`
- Constructor accepts: `host`, `port`, `database`, `username`, `password`, `ssl`, `tls_ca_file`
- LLM-callable tools:
  - `search_collections(search_term, limit)` — discover collections
  - `generate_mql_query(natural_language, collection)` — generate MongoDB query from description
  - `execute_query(collection, query_filter, projection, limit)` → `QueryExecutionResponse`
  - `explore_collection(collection_name)` — get collection schema/stats
- `start()` → connect via asyncdb documentdb driver
- Port collection metadata extraction from `parrot/bots/db/documentdb.py`
- Write unit tests

**NOT in scope**: SQL databases, agent integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/database/toolkits/documentdb.py` | CREATE | DocumentDBToolkit implementation |
| `parrot/bots/database/toolkits/__init__.py` | MODIFY | Add DocumentDBToolkit export |
| `tests/unit/test_documentdb_toolkit.py` | CREATE | Unit tests |

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
# parrot/bots/db/documentdb.py (lines 57-200+) — port from here
# class DocumentDBAgent(AbstractDBAgent):
#   host: str, port: int = 27017, database: str
#   username: str, password: str, ssl: bool = True, tls_ca_file: str
#   db_connection: Optional[Any]
#   collections_cache: Dict[str, CollectionMetadata]
```

### Does NOT Exist
- ~~`DocumentDBToolkit`~~ — does not exist yet (this task creates it)
- ~~`CollectionMetadata` in models.py~~ — only in `bots/db/documentdb.py`; define locally or add to models

---

## Acceptance Criteria

- [ ] `DocumentDBToolkit` inherits from `DatabaseToolkit`
- [ ] `search_collections()`, `execute_query()`, `explore_collection()` are LLM-callable tools
- [ ] All tests pass: `pytest tests/unit/test_documentdb_toolkit.py -v`
- [ ] Imports work: `from parrot.bots.database.toolkits import DocumentDBToolkit`

---

## Test Specification

```python
import pytest
from parrot.bots.database.toolkits.documentdb import DocumentDBToolkit
from parrot.bots.database.toolkits.base import DatabaseToolkit


class TestDocumentDBToolkit:
    def test_inherits_database_toolkit(self):
        assert issubclass(DocumentDBToolkit, DatabaseToolkit)

    def test_tool_methods(self):
        tk = DocumentDBToolkit(
            dsn="mongodb://localhost:27017/test", backend="asyncdb"
        )
        tool_names = [t.name for t in tk.get_tools()]
        assert "search_collections" in tool_names
        assert "execute_query" in tool_names
        assert "explore_collection" in tool_names
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — verify TASK-569 is completed
2. **Read `parrot/bots/db/documentdb.py`** — primary source to port from
3. **Implement**, test, move to completed, update index

---

## Completion Note

*(Agent fills this in when done)*
