# Brainstorm: DatabaseLoader — Load Database Tables as RAG Documents

**Date**: 2026-04-14
**Author**: Claude Code
**Status**: exploration
**Recommended Option**: A

---

## Jira Source

| Field | Value |
|-------|-------|
| Key | NAV-7712 |
| Summary | ATT360 - Product Module (Prepaid Devices Only) |
| Type | Story |
| Priority | Major |
| Components | AT&T |
| Complexity | simple |

---

## Problem Statement

Product data (AT&T plans: plan_name, price, specifications) lives in a PostgreSQL
table (`att.plans`) and needs to be ingested into the RAG pipeline as Documents.
Currently there is no loader that can read directly from a database table — all
existing loaders consume files (CSV, PDF, etc.) or URLs.

More broadly, any structured data in PostgreSQL (or other databases supported by
AsyncDB) should be loadable into Documents without requiring an intermediate CSV
export. A generic `DatabaseLoader` would serve the AT&T plans use case and any
future table-based ingestion.

**User Notes (verbatim):**
> There is a product (plans) information in a postgres table (att.plans) with
> plan_name, price and specifications (a list of strings). Create a new
> DatabaseLoader inheriting from AbstractLoader, using table information to
> create a Document per-row, iterating over all columns but removing
> created_at/updated_at/inserted_at. Uses AsyncDB with request driver
> (default=pg) and params or dsn (default from parrot.conf.default_dsn),
> schema (default=public) and table (required). Returns List[Document].

## Constraints & Requirements

- Must inherit from `AbstractLoader` and implement `async _load()`.
- Uses `AsyncDB` (not raw asyncpg) — driver is configurable (`'pg'` default).
- Connection via `async with await db.connection() as conn`.
- DSN defaults to `parrot.conf.default_dsn`; overridable via constructor.
- `table` is **required**; `schema` defaults to `public`.
- Automatically drops `created_at`, `updated_at`, `inserted_at` columns from content.
- `page_content` format: YAML by default, JSON optional (`content_format` param).
- List/array columns (PostgreSQL arrays, JSONB): expanded as bullet lists in YAML, kept as arrays in JSON.
- NULL values rendered as `null` (not omitted).
- Optional `where` clause for row filtering.
- `Document.metadata` includes: table name, schema, row_index, source (`{schema}.{table}`), driver name.
- File location: `parrot_loaders/database.py`, registered in `LOADER_REGISTRY`.

---

## Options Explored

### Option A: AsyncDB-Based Generic DatabaseLoader

A single `DatabaseLoader` class that uses AsyncDB to connect to any supported
database, runs `SELECT * FROM {schema}.{table}` (with optional WHERE), iterates
rows via the driver's native record type, and serializes each row into a Document.

The loader constructs the query dynamically from `schema`, `table`, and `where`
parameters. Column filtering (dropping timestamp columns) happens in Python after
fetching, keeping the SQL simple and portable across drivers.

Content serialization supports two formats: YAML (default) and JSON. For YAML,
list-type columns are expanded as bullet lists. For JSON, native arrays are
preserved.

**Jira AC coverage**: The Jira ticket has no formal AC, but the user notes
describe all requirements. This option covers them fully.

✅ **Pros:**
- Simple, single-class design — easy to understand and maintain.
- AsyncDB abstraction means it works with PostgreSQL, MySQL, SQLite, etc.
- YAML output produces human-readable content ideal for LLM consumption.
- Follows the exact same pattern as CSVLoader (one Document per row).
- Column exclusion list is configurable, not hardcoded.

❌ **Cons:**
- No streaming for very large tables (loads all rows into memory).
- SQL injection risk if `where` clause is passed as raw string (mitigated by AsyncDB parameterization where possible, but custom WHERE is inherently risky).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | Async database connectivity | Already a project dependency; provides `AsyncDB('pg', ...)` |
| `pyyaml` / `yaml` | YAML serialization | Standard library-adjacent; likely already available |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/loaders/abstract.py` — AbstractLoader base class, `create_metadata()`, `create_document()`.
- `packages/ai-parrot-loaders/src/parrot_loaders/csv.py` — CSVLoader pattern (one Document per row, row_index metadata, JSON serialization).
- `packages/ai-parrot/src/parrot/conf.py:56` — `default_dsn` for default connection string.
- `packages/ai-parrot/src/parrot/stores/models.py:21` — `Document(page_content, metadata)`.

---

### Option B: Query-Based Loader (SQL as Source)

Instead of `table` + `schema` + `where`, accept a raw SQL query as the `source`
parameter. The user writes `SELECT plan_name, price, specifications FROM att.plans
WHERE ...` and the loader executes it, creating Documents from each result row.

This is closer to the existing `SQLDataSource` extractor pattern but adapted
for the loader pipeline.

✅ **Pros:**
- Maximum flexibility — user controls exactly what data is fetched.
- No need to implement column filtering — user selects only what they want.
- Supports JOINs, aggregations, subqueries.

❌ **Cons:**
- Shifts complexity to the caller (must write SQL).
- Harder to auto-generate metadata (no table name, schema, PK).
- SQL injection risk is higher (entire query is user-provided).
- Doesn't match the user's request for a table-based interface.
- Read-only validation needed (like SQLDataSource's mutation pattern check).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | Async database connectivity | Same as Option A |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-loaders/src/parrot_loaders/extractors/sql_source.py` — `SQLDataSource` pattern, mutation detection regex.
- `packages/ai-parrot/src/parrot/loaders/abstract.py` — AbstractLoader base.

---

### Option C: Hybrid — Table Mode + Query Mode

Combine Option A and Option B: the loader accepts either a `table` parameter
(auto-generates SELECT) or a `query` parameter (raw SQL). If both are provided,
`query` takes precedence.

This gives the simple table-based interface for common cases and the full SQL
escape hatch for complex scenarios.

✅ **Pros:**
- Best of both worlds — simple for common cases, flexible for advanced.
- A single class handles all database-to-document needs.
- `table` mode generates clean metadata; `query` mode falls back to generic metadata.

❌ **Cons:**
- More complex constructor (two mutually-exclusive code paths).
- Risk of confusing API surface ("do I use table or query?").
- More testing surface.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncdb` | Async database connectivity | Same as Option A |

🔗 **Existing Code to Reuse:**
- Same as Option A + Option B combined.

---

## Recommendation

**Option A** is recommended because:

- The user explicitly asked for a table-based interface, not a query-based one.
- The `where` parameter provides sufficient filtering without exposing full SQL.
- Keeps the API surface minimal and consistent with other loaders (CSVLoader takes a file path, DatabaseLoader takes a table name).
- Option B's query mode can be added later as an enhancement if needed — the architecture doesn't preclude it.
- Low effort means fast delivery for the AT&T plans use case.

---

## Feature Description

### User-Facing Behavior

```python
from parrot.loaders import DatabaseLoader

# Minimal usage — load entire table
loader = DatabaseLoader(table='plans', schema='att')
docs = await loader.load()

# With filtering
loader = DatabaseLoader(
    table='plans',
    schema='att',
    where="plan_name NOT LIKE '%Online Only%'",
    content_format='json',
)
docs = await loader.load()

# With custom DSN and driver
loader = DatabaseLoader(
    table='products',
    driver='pg',
    dsn='postgres://user:pass@host:5432/mydb',
    exclude_columns=['internal_notes', 'created_at'],
)
docs = await loader.load()
```

Each returned `Document` has:
- `page_content`: YAML or JSON representation of the row (minus excluded columns).
- `metadata`: table name, schema, row_index, source, driver.

### Internal Behavior

1. **Constructor**: Stores `table`, `schema`, `driver`, `dsn`, `where`, `content_format`, `exclude_columns`. Defaults `dsn` from `parrot.conf.default_dsn`.
2. **`_load()`**: 
   - Creates `AsyncDB(driver, dsn=dsn)` or `AsyncDB(driver, params=params)`.
   - Opens connection via `async with await db.connection() as conn`.
   - Builds query: `SELECT * FROM {schema}.{table}` + optional `WHERE {where}` clause.
   - Executes query, iterates over result rows.
   - For each row: filters out excluded columns, serializes remaining columns to YAML/JSON, creates Document with metadata.
3. **Column serialization**: 
   - Scalar values → key: value.
   - `list` values (from PostgreSQL arrays/JSONB) → bullet list in YAML, array in JSON.
   - `None` → `null`.
4. **Returns** `List[Document]`.

### Edge Cases & Error Handling

- **Empty table**: Returns empty list, logs warning.
- **Connection failure**: Raises with clear message including DSN (masked password) and driver.
- **Invalid table/schema**: Database raises error — propagate with context.
- **Large tables**: All rows loaded into memory. For very large tables, caller should use `where` with LIMIT/OFFSET. Future enhancement could add `batch_size` support.
- **Column type handling**: AsyncDB/asyncpg handles PostgreSQL type → Python type natively (arrays → lists, JSONB → dicts, etc.). No manual casting needed.

---

## Capabilities

### New Capabilities
- `database-loader`: Load database table rows as RAG Documents via AsyncDB.

### Modified Capabilities
- None.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_loaders` package | extends | New file `database.py` + registry entry |
| `LOADER_REGISTRY` | extends | Add `"DatabaseLoader": "parrot_loaders.database.DatabaseLoader"` |
| `parrot.conf` | depends on | Uses `default_dsn` for default connection |
| `asyncdb` | depends on | External dependency (already in project) |

---

## Code Context

### User-Provided Code

```python
# Source: user-provided (from -- notes)
# Usage pattern described by user:
from parrot.stores.models import Document
from parrot.conf import default_dsn
# Uses AsyncDB: db = AsyncDB('pg', **params)
# Connection: async with await db.connection() as conn
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/loaders/abstract.py:36
class AbstractLoader(ABC):
    extensions: List[str] = ['.*']  # line 41
    skip_directories: List[str] = []  # line 42

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        tokenizer: Union[str, Callable] = None,
        text_splitter: Union[str, Callable] = None,
        source_type: str = 'file',
        **kwargs
    ):  # line 44-50

    @abstractmethod
    async def _load(self, source: Union[str, PurePath], **kwargs) -> List[Document]:  # line 460
        ...

    def create_metadata(
        self,
        path: Union[str, PurePath],
        doctype: str = 'document',
        source_type: str = 'source',
        doc_metadata: Optional[dict] = None,
        **kwargs
    ):  # line 717

    def create_document(
        self,
        content: Any,
        path: Union[str, PurePath],
        metadata: Optional[dict] = None,
        **kwargs
    ) -> Document:  # line 750
```

```python
# From packages/ai-parrot/src/parrot/stores/models.py:21
class Document(BaseModel):
    page_content: str  # line 26
    metadata: Dict[str, Any] = Field(default_factory=dict)  # line 27
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.loaders import AbstractLoader  # packages/ai-parrot/src/parrot/loaders/__init__.py
from parrot.stores.models import Document  # packages/ai-parrot/src/parrot/stores/models.py:21
from parrot.conf import default_dsn  # packages/ai-parrot/src/parrot/conf.py:56
# default_dsn = f'postgres://{DBUSER}:{DBPWD}@{DBHOST}:{DBPORT}/{DBNAME}'
```

#### Key Attributes & Constants
- `default_dsn` → `str` (parrot/conf.py:56) — format: `postgres://user:pwd@host:port/dbname`
- `AbstractLoader.create_metadata()` → returns `dict` (parrot/loaders/abstract.py:717)
- `AbstractLoader.create_document()` → returns `Document` (parrot/loaders/abstract.py:750)
- `LOADER_REGISTRY` → `dict[str, str]` (parrot_loaders/__init__.py:9)

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.loaders.DatabaseLoader`~~ — does not exist yet (this brainstorm creates it)
- ~~`parrot.loaders.SQLLoader`~~ — does not exist
- ~~`parrot_loaders.database`~~ — module does not exist yet
- ~~`AbstractLoader.from_database()`~~ — no such method on the base class
- ~~`parrot.conf.async_default_dsn`~~ — exists but is SQLAlchemy-format (`postgresql+asyncpg://`), NOT the one to use with AsyncDB. Use `default_dsn` instead.

---

## Parallelism Assessment

- **Internal parallelism**: No — this is a single-file, single-class feature. One task.
- **Cross-feature independence**: No conflicts with in-flight specs. Only touches new file + registry.
- **Recommended isolation**: per-spec (single worktree, single task).
- **Rationale**: The feature is self-contained (one new file + one registry line). No reason to split.

---

## Open Questions

- [x] Verify `asyncdb` is listed in `pyproject.toml` dependencies for `ai-parrot-loaders` package — *Owner: developer*: Yes, already exists.
- [x] Confirm `yaml` (PyYAML) is available in the loaders package — *Owner: developer*: Yes, already exists.
