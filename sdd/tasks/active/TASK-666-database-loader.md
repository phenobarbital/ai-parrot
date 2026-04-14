# TASK-666: Implement DatabaseLoader and Register in LOADER_REGISTRY

**Feature**: NAV-7712-database-loader
**Spec**: `sdd/specs/NAV-7712-database-loader.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the sole implementation task for FEAT-099 — DatabaseLoader. It covers
the spec's Module 1 (DatabaseLoader class) and Module 2 (registry entry) since
the registry update is a single line and inseparable from the loader.

Implements Spec Sections 2 (Architectural Design), 3 (Module Breakdown), and 4
(Test Specification).

---

## Scope

- Implement `DatabaseLoader` class in `parrot_loaders/database.py`:
  - Inherits from `AbstractLoader`.
  - Constructor accepts: `table` (required), `schema` (default `'public'`),
    `driver` (default `'pg'`), `dsn` (default from `parrot.conf.default_dsn`),
    `params` (optional dict), `where` (optional string), `content_format`
    (default `'yaml'`, also `'json'`), `exclude_columns` (default
    `['created_at', 'updated_at', 'inserted_at']`).
  - Implements `async _load()`:
    1. Creates `AsyncDB(driver, dsn=dsn)` or `AsyncDB(driver, params=params)`.
    2. Opens connection via `async with await db.connection() as conn`.
    3. Builds query: `SELECT * FROM {schema}.{table}` + optional `WHERE {where}`.
    4. Iterates result rows, filters excluded columns, serializes to YAML or JSON.
    5. For YAML: list/array values expanded as bullet lists; NULL as `null`.
    6. For JSON: arrays preserved natively; NULL as `null`.
    7. Creates `Document(page_content, metadata)` per row.
    8. Returns `List[Document]`.
  - Metadata per document: `table`, `schema`, `row_index`, `source` (`{schema}.{table}`), `driver`.
  - Empty table returns `[]` with logged warning.
- Add `"DatabaseLoader": "parrot_loaders.database.DatabaseLoader"` to `LOADER_REGISTRY`
  in `parrot_loaders/__init__.py`.
- Write unit tests covering: init defaults, required table, column exclusion,
  YAML serialization, JSON serialization, null handling, list expansion, empty table,
  WHERE clause construction.

**NOT in scope**:
- Query-mode (raw SQL as source) — future enhancement.
- Streaming/cursor-based loading for large tables.
- Primary key discovery via information_schema.
- Integration tests requiring a live database (manual verification only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/database.py` | CREATE | DatabaseLoader implementation |
| `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py` | MODIFY | Add `"DatabaseLoader"` to `LOADER_REGISTRY` |
| `tests/test_database_loader.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# For the DatabaseLoader implementation:
from parrot.loaders import AbstractLoader       # packages/ai-parrot/src/parrot/loaders/__init__.py
from parrot.stores.models import Document        # packages/ai-parrot/src/parrot/stores/models.py:21
from parrot.conf import default_dsn              # packages/ai-parrot/src/parrot/conf.py:56

# External:
from asyncdb import AsyncDB                     # asyncdb package (project dependency)
import yaml                                     # PyYAML (project dependency)
import json                                     # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/loaders/abstract.py:36
class AbstractLoader(ABC):
    extensions: List[str] = ['.*']                            # line 41
    skip_directories: List[str] = []                          # line 42

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'file',
        **kwargs
    ):                                                        # line 44-52
        self.chunk_size: int = kwargs.get('chunk_size', 2048) # line 63
        self.chunk_overlap: int = kwargs.get('chunk_overlap', 200) # line 64
        self.encoding = kwargs.get('encoding', 'utf-8')       # line 73

    @abstractmethod
    async def _load(
        self, source: Union[str, PurePath], **kwargs
    ) -> List[Document]:                                      # line 460

    def create_metadata(
        self,
        path: Union[str, PurePath],
        doctype: str = 'document',
        source_type: str = 'source',
        doc_metadata: Optional[dict] = None,
        **kwargs
    ):                                                        # line 717
        # Returns dict with: url, source, filename, type, source_type,
        # created_at, category, document_meta

    def create_document(
        self,
        content: Any,
        path: Union[str, PurePath],
        metadata: Optional[dict] = None,
        **kwargs
    ) -> Document:                                            # line 750
        # Returns Document(page_content=content, metadata=_meta)
```

```python
# packages/ai-parrot/src/parrot/stores/models.py:21
class Document(BaseModel):
    page_content: str                                         # line 26
    metadata: Dict[str, Any] = Field(default_factory=dict)    # line 27
```

```python
# packages/ai-parrot/src/parrot/conf.py:56
default_dsn = f'postgres://{DBUSER}:{DBPWD}@{DBHOST}:{DBPORT}/{DBNAME}'
```

```python
# packages/ai-parrot-loaders/src/parrot_loaders/__init__.py:9
LOADER_REGISTRY: dict[str, str] = {
    # ... existing entries ...
    # ADD HERE: "DatabaseLoader": "parrot_loaders.database.DatabaseLoader",
}
```

### Does NOT Exist
- ~~`parrot.loaders.DatabaseLoader`~~ — does not exist yet (this task creates it)
- ~~`parrot.loaders.SQLLoader`~~ — does not exist
- ~~`parrot_loaders.database`~~ — module does not exist yet
- ~~`AbstractLoader.from_database()`~~ — no such method on the base class
- ~~`AbstractLoader.from_query()`~~ — no such method
- ~~`parrot.conf.async_default_dsn`~~ — exists (conf.py:57) but is SQLAlchemy-format (`postgresql+asyncpg://`), NOT compatible with AsyncDB. Use `default_dsn` instead.

---

## Implementation Notes

### Pattern to Follow
```python
# Follow CSVLoader pattern from packages/ai-parrot-loaders/src/parrot_loaders/csv.py
# Key structure:
class CSVLoader(AbstractLoader):
    def __init__(self, source=None, *, source_type='file', **kwargs):
        super().__init__(source, source_type=source_type, **kwargs)
        # ... store config ...

    async def _load(self, path, **kwargs) -> List[Document]:
        docs = []
        # ... iterate rows ...
        for row_index, row in enumerate(rows):
            json_content = self._format_row(row_dict)
            metadata = self.create_metadata(
                path=path,
                doctype="csv_row",
                source_type="csv",
                doc_metadata={
                    "row_index": row_index,
                    # ...
                },
            )
            doc = Document(page_content=json_content, metadata=metadata)
            docs.append(doc)
        return docs
```

### Row Serialization

**YAML mode** (`content_format='yaml'`):
```yaml
plan_name: Unlimited Saver
price: 35.0
specifications:
- 5G access
- Unlimited talk & text
active: null
```

**JSON mode** (`content_format='json'`):
```json
{"plan_name": "Unlimited Saver", "price": 35.0, "specifications": ["5G access", "Unlimited talk & text"], "active": null}
```

### Key Constraints
- Must be async throughout.
- Use `self.logger` for all logging (inherited from AbstractLoader).
- Use `create_metadata()` for consistent metadata structure.
- Pass `source_type='database'` and `doctype='db_row'`.
- The `source` parameter passed to `_load()` by the base class may not be meaningful for database loading. Use the instance's `table`/`schema` attributes to build the query.
- The `where` clause is appended as raw SQL. Log a warning when it is used.

### AsyncDB Connection Pattern
```python
# AsyncDB usage (verified from project patterns):
db = AsyncDB(driver, dsn=dsn)
# OR with params dict:
db = AsyncDB(driver, params=params)

# Connection lifecycle:
async with await db.connection() as conn:
    result = await conn.fetch(query)
    # result is a list of Record objects (dict-like)
```

### References in Codebase
- `packages/ai-parrot-loaders/src/parrot_loaders/csv.py` — CSVLoader (primary pattern)
- `packages/ai-parrot-loaders/src/parrot_loaders/extractors/sql_source.py` — SQLDataSource (AsyncDB usage pattern, mutation detection)
- `packages/ai-parrot/src/parrot/loaders/abstract.py` — AbstractLoader base

---

## Acceptance Criteria

- [ ] `DatabaseLoader` inherits from `AbstractLoader` and implements `async _load()`
- [ ] Constructor requires `table`, defaults `schema='public'`, `driver='pg'`, `dsn` from `default_dsn`
- [ ] Uses `AsyncDB(driver, dsn=dsn)` with `async with await db.connection() as conn`
- [ ] Generates `SELECT * FROM {schema}.{table}` with optional `WHERE {where}`
- [ ] Excludes `created_at`, `updated_at`, `inserted_at` by default (configurable)
- [ ] `page_content` defaults to YAML; JSON available via `content_format='json'`
- [ ] List columns expanded as bullet lists in YAML, preserved as arrays in JSON
- [ ] NULL values rendered as `null`
- [ ] `Document.metadata` includes: table, schema, row_index, source, driver
- [ ] Empty table returns `[]` with logged warning
- [ ] Registered in `LOADER_REGISTRY`
- [ ] Unit tests pass: `pytest tests/test_database_loader.py -v`
- [ ] Imports work: `from parrot_loaders.database import DatabaseLoader`

---

## Test Specification

```python
# tests/test_database_loader.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot_loaders.database import DatabaseLoader


@pytest.fixture
def loader():
    return DatabaseLoader(table='plans', schema='att')


@pytest.fixture
def sample_rows():
    """Simulated database rows as list of dicts."""
    return [
        {
            "plan_name": "Unlimited Saver",
            "price": 35.0,
            "specifications": ["5G access", "Unlimited talk & text"],
            "created_at": "2026-01-01",
        },
        {
            "plan_name": "Unlimited Ultra",
            "price": 60.0,
            "specifications": ["5G+ access", "50GB hotspot"],
            "created_at": "2026-01-01",
        },
    ]


class TestDatabaseLoaderInit:
    def test_defaults(self, loader):
        assert loader.table == 'plans'
        assert loader.schema == 'att'
        assert loader.driver == 'pg'
        assert loader.content_format == 'yaml'

    def test_required_table(self):
        with pytest.raises(TypeError):
            DatabaseLoader()

    def test_default_exclude_columns(self, loader):
        assert 'created_at' in loader.exclude_columns
        assert 'updated_at' in loader.exclude_columns
        assert 'inserted_at' in loader.exclude_columns

    def test_custom_exclude(self):
        loader = DatabaseLoader(table='t', exclude_columns=['internal'])
        assert 'internal' in loader.exclude_columns


class TestSerialization:
    def test_yaml_format(self, loader):
        row = {"name": "Test", "price": 10.0, "tags": ["a", "b"]}
        content = loader._serialize_row(row)
        assert "name: Test" in content
        assert "- a" in content
        assert "- b" in content

    def test_json_format(self):
        loader = DatabaseLoader(table='t', content_format='json')
        row = {"name": "Test", "tags": ["a", "b"]}
        content = loader._serialize_row(row)
        import json
        parsed = json.loads(content)
        assert parsed["tags"] == ["a", "b"]

    def test_null_values(self, loader):
        row = {"name": "Test", "email": None}
        content = loader._serialize_row(row)
        assert "null" in content

    def test_exclude_columns(self, loader):
        row = {"name": "Test", "created_at": "2026-01-01", "price": 10}
        filtered = loader._filter_columns(row)
        assert "created_at" not in filtered
        assert "name" in filtered
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/NAV-7712-database-loader.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` -> `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-666-database-loader.md`
8. **Update index** -> `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
