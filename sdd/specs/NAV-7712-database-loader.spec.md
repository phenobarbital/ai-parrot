# Feature Specification: DatabaseLoader — Load Database Tables as RAG Documents

**Feature ID**: FEAT-099
**Jira**: [NAV-7712](https://trocglobal.atlassian.net/browse/NAV-7712)
**Date**: 2026-04-14
**Author**: Claude Code
**Status**: draft
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

Product data (e.g., AT&T prepaid plans with plan_name, price, specifications) lives
in PostgreSQL tables and needs to be ingested into the RAG pipeline as Documents.
All existing loaders consume files (CSV, PDF, HTML) or URLs — none can read
directly from a database table. This forces a manual CSV export step that is
fragile, stale, and unnecessary.

A generic `DatabaseLoader` would serve the immediate AT&T plans use case
(`att.plans` table) and any future table-based ingestion across projects.

### Goals
- Provide a `DatabaseLoader` that loads any database table into `List[Document]`.
- Support AsyncDB with configurable driver (PostgreSQL default, others available).
- Produce one Document per row with YAML (default) or JSON serialization.
- Follow the same AbstractLoader contract as all other loaders.
- Register in `LOADER_REGISTRY` for discovery.

### Non-Goals (explicitly out of scope)
- Streaming/cursor-based loading for very large tables (future enhancement).
- Query-mode (raw SQL) — table-based interface only in v1.
- Write/mutation operations — this is strictly read-only.
- Primary key discovery via `information_schema` (dropped per user decision).

---

## 2. Architectural Design

### Overview

`DatabaseLoader` inherits from `AbstractLoader` and implements `_load()`. It uses
`AsyncDB` to connect to a database, executes `SELECT * FROM {schema}.{table}`
(with optional WHERE clause), iterates result rows, and serializes each row into
a `Document` with YAML or JSON `page_content` and structured metadata.

### Component Diagram
```
DatabaseLoader
    │
    ├── __init__(table, schema, driver, dsn, where, content_format, exclude_columns)
    │
    └── _load(source)
            │
            ├── AsyncDB(driver, dsn=dsn)
            │       └── async with await db.connection() as conn
            │               └── conn.fetch(SELECT * FROM schema.table WHERE ...)
            │
            ├── for each row:
            │       ├── filter out exclude_columns
            │       ├── serialize to YAML or JSON
            │       │       └── expand list/array columns as bullet lists (YAML)
            │       │       └── keep arrays as-is (JSON)
            │       └── create Document(page_content, metadata)
            │
            └── return List[Document]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractLoader` | extends | Inherits base class, implements `_load()` |
| `Document` | uses | Creates instances from `parrot.stores.models` |
| `default_dsn` | depends on | Default connection string from `parrot.conf` |
| `AsyncDB` | depends on | External library for async database connectivity |
| `LOADER_REGISTRY` | extends | Adds `"DatabaseLoader"` entry |

### Data Models

No new Pydantic models. Uses existing `Document(page_content: str, metadata: dict)`.

### New Public Interfaces

```python
class DatabaseLoader(AbstractLoader):
    """Load database table rows as RAG Documents via AsyncDB."""

    def __init__(
        self,
        table: str,
        *,
        schema: str = 'public',
        driver: str = 'pg',
        dsn: Optional[str] = None,
        params: Optional[dict] = None,
        where: Optional[str] = None,
        content_format: str = 'yaml',  # 'yaml' or 'json'
        exclude_columns: Optional[List[str]] = None,
        source_type: str = 'database',
        **kwargs
    ): ...

    async def _load(
        self,
        source: Union[str, PurePath],
        **kwargs
    ) -> List[Document]: ...
```

---

## 3. Module Breakdown

### Module 1: DatabaseLoader
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/database.py`
- **Responsibility**: Connect to database, fetch table rows, serialize to Documents.
- **Depends on**: `AbstractLoader`, `AsyncDB`, `Document`, `parrot.conf.default_dsn`

### Module 2: Registry Update
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py`
- **Responsibility**: Add `"DatabaseLoader": "parrot_loaders.database.DatabaseLoader"` to `LOADER_REGISTRY`.
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_init_defaults` | Module 1 | Validates defaults: schema='public', driver='pg', dsn=default_dsn, content_format='yaml' |
| `test_init_required_table` | Module 1 | Raises if `table` is not provided |
| `test_exclude_columns_default` | Module 1 | Default excludes `created_at`, `updated_at`, `inserted_at` |
| `test_exclude_columns_custom` | Module 1 | Custom exclude_columns overrides defaults |
| `test_serialize_yaml` | Module 1 | Row dict serialized as YAML with list expansion |
| `test_serialize_json` | Module 1 | Row dict serialized as JSON with arrays preserved |
| `test_null_values` | Module 1 | NULL columns rendered as `null` in both formats |
| `test_list_column_yaml` | Module 1 | PostgreSQL array/list expanded as bullet list in YAML |
| `test_list_column_json` | Module 1 | PostgreSQL array/list kept as JSON array |
| `test_empty_table` | Module 1 | Returns empty list, logs warning |
| `test_where_clause` | Module 1 | WHERE clause appended to query correctly |

### Integration Tests
| Test | Description |
|---|---|
| `test_load_real_table` | Load from an actual PostgreSQL table (requires DB fixture) |
| `test_load_with_where` | Load with WHERE filter, verify filtered results |
| `test_registry_discovery` | `LOADER_REGISTRY["DatabaseLoader"]` resolves to correct class |

### Test Data / Fixtures
```python
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
            "specifications": ["5G+ access", "50GB hotspot", "Unlimited talk & text"],
            "created_at": "2026-01-01",
        },
    ]
```

---

## 5. Acceptance Criteria

- [ ] `DatabaseLoader` inherits from `AbstractLoader` and implements `async _load()`.
- [ ] Constructor requires `table`, defaults `schema='public'`, `driver='pg'`, `dsn` from `parrot.conf.default_dsn`.
- [ ] Uses `AsyncDB(driver, dsn=dsn)` with `async with await db.connection() as conn` lifecycle.
- [ ] Generates `SELECT * FROM {schema}.{table}` with optional `WHERE {where}`.
- [ ] Excludes `created_at`, `updated_at`, `inserted_at` columns by default (configurable).
- [ ] `page_content` defaults to YAML format; JSON available via `content_format='json'`.
- [ ] List/array columns expanded as bullet lists in YAML, preserved as arrays in JSON.
- [ ] NULL values rendered as `null` (not omitted).
- [ ] `Document.metadata` includes: table, schema, row_index, source (`{schema}.{table}`), driver.
- [ ] Empty table returns `[]` with a logged warning.
- [ ] Registered in `LOADER_REGISTRY` as `"DatabaseLoader": "parrot_loaders.database.DatabaseLoader"`.
- [ ] Unit tests pass for serialization, column filtering, and edge cases.
- [ ] No breaking changes to existing loaders or public API.

---

## 6. Codebase Contract

### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.loaders import AbstractLoader       # packages/ai-parrot/src/parrot/loaders/__init__.py
from parrot.stores.models import Document        # packages/ai-parrot/src/parrot/stores/models.py:21
from parrot.conf import default_dsn              # packages/ai-parrot/src/parrot/conf.py:56
# default_dsn = f'postgres://{DBUSER}:{DBPWD}@{DBHOST}:{DBPORT}/{DBNAME}'

# External:
from asyncdb import AsyncDB                     # asyncdb package (project dependency)
```

### Existing Class Signatures
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
        # ... (many more kwargs processed)

    @abstractmethod
    async def _load(
        self, source: Union[str, PurePath], **kwargs
    ) -> List[Document]:                                      # line 460
        ...

    def create_metadata(
        self,
        path: Union[str, PurePath],
        doctype: str = 'document',
        source_type: str = 'source',
        doc_metadata: Optional[dict] = None,
        **kwargs
    ):                                                        # line 717
        # Returns dict with keys: url, source, filename, type, source_type,
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

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `DatabaseLoader.__init__()` | `AbstractLoader.__init__()` | `super().__init__()` | `abstract.py:44` |
| `DatabaseLoader._load()` | `AbstractLoader._load()` | abstract method impl | `abstract.py:460` |
| `DatabaseLoader._load()` | `AbstractLoader.create_metadata()` | method call | `abstract.py:717` |
| `DatabaseLoader._load()` | `Document()` | constructor | `models.py:21` |
| `DatabaseLoader.__init__()` | `parrot.conf.default_dsn` | default param | `conf.py:56` |
| `LOADER_REGISTRY` | `DatabaseLoader` | registry entry | `parrot_loaders/__init__.py:9` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.loaders.DatabaseLoader`~~ — does not exist yet (this spec creates it)
- ~~`parrot.loaders.SQLLoader`~~ — does not exist
- ~~`parrot_loaders.database`~~ — module does not exist yet
- ~~`AbstractLoader.from_database()`~~ — no such method on the base class
- ~~`AbstractLoader.from_query()`~~ — no such method
- ~~`parrot.conf.async_default_dsn`~~ — exists (`conf.py:57`) but is SQLAlchemy-format (`postgresql+asyncpg://`), NOT compatible with AsyncDB. Use `default_dsn` instead.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Follow `CSVLoader` pattern (`parrot_loaders/csv.py`) for one-Document-per-row structure.
- Use `self.logger` for all logging (inherited from AbstractLoader).
- Use `create_metadata()` for consistent metadata structure.
- Pass `source_type='database'` to distinguish from file-based loaders.

### Row Serialization Logic

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

For YAML: list values are expanded as bullet lists. For JSON: arrays are preserved natively.

### Known Risks / Gotchas
- **SQL injection via `where` parameter**: The `where` clause is appended as a raw string. AsyncDB parameterization may not cover arbitrary WHERE expressions. Document that callers should sanitize input. Consider logging a warning when `where` is used.
- **Large tables**: No pagination in v1. Callers should use `WHERE ... LIMIT N` for large tables.
- **`source` parameter in `_load()`**: AbstractLoader passes `source` to `_load()`. For DatabaseLoader, `source` is the table reference (`{schema}.{table}`), not a file path. The `_load()` implementation should use the instance's `table`/`schema` attributes rather than the `source` parameter.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `asyncdb` | (project dependency) | Async database connectivity with pluggable drivers |
| `pyyaml` | (project dependency) | YAML serialization for `content_format='yaml'` |

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Parallelizable tasks**: None — single implementation file + registry update.
- **Cross-feature dependencies**: None. This spec touches only new files and one existing registry.

---

## 8. Open Questions

All questions resolved during brainstorm Q&A. No open items remain.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-14 | Claude Code | Initial draft from brainstorm NAV-7712 |
