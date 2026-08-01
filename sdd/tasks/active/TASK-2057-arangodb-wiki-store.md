# TASK-2057: Implement ArangoDBWikiStore

**Feature**: FEAT-400 — WikiToolkit ArangoDB Backend
**Spec**: `sdd/specs/wikitoolkit-arangodb-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the core task — implements the new ArangoDB-backed wiki retrieval
plane. Corresponds to Module 1 in the spec. All other tasks depend on this
class existing.

---

## Scope

- Implement `ArangoDBWikiStore(BaseWikiStore)` in a new file
  `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py`.
- Implement all 15 abstract methods from `BaseWikiStore` using AQL queries
  and ArangoSearch views via the `asyncdb` ArangoDB driver.
- Implement `__init__`, `initialize()` (async — creates database,
  collections, ArangoSearch view), and `close()`.
- Create 5 ArangoDB collections: `wiki_pages`, `wiki_edges`,
  `wiki_embeddings`, `wiki_sources`, `wiki_meta`.
- Create an ArangoSearch view (`{wiki_name}_pages_view`) with a
  configurable text analyzer on `title`, `summary`, `body` fields.
- Use `rank_by_cosine()` from `store.py` for vector search.
- Use `estimate_tokens()` from `store.py` for token counting.
- Write unit tests with mocked asyncdb driver.

**NOT in scope**:
- Config model changes (TASK-2058)
- Factory wiring (TASK-2059)
- SourceCollectionManager changes (TASK-2060)
- CLI integration (TASK-2061)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` | CREATE | ArangoDBWikiStore implementation |
| `tests/knowledge/wiki/test_arango_store.py` | CREATE | Unit tests (mocked asyncdb) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.store import BaseWikiStore       # verified: store.py:279
from parrot.knowledge.wiki.store import WikiPageRecord       # verified: store.py:205
from parrot.knowledge.wiki.store import rank_by_cosine       # verified: store.py:236
from parrot.knowledge.wiki.store import estimate_tokens      # verified: store.py:153
from asyncdb import AsyncDB                                  # verified: used in ontology/graph_store.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):  # line 279
    # Write methods
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...          # line 298
    async def add_edges(self, edges: list[tuple]) -> int: ...                      # line 301
    async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord],
        edges: Optional[list[tuple[str, str, str]]] = None) -> dict[str, Any]: ... # line 304
    async def delete_page(self, concept_id: str) -> bool: ...                      # line 312
    async def upsert_embedding(self, concept_id: str, vector: list[float],
        model: str = "") -> None: ...                                              # line 315
    # Read methods
    async def get_page(self, concept_id: str,
        include_body: bool = True) -> Optional[dict[str, Any]]: ...                # line 321
    async def list_pages(self, category: Optional[str] = None, limit: int = 100,
        origin: Optional[list[str]] = None) -> list[dict[str, Any]]: ...           # line 326
    async def search_fts(self, query: str, category: Optional[str] = None,
        limit: int = 10) -> list[dict[str, Any]]: ...                              # line 334
    async def search_vector(self, embedding: list[float],
        limit: int = 10) -> list[dict[str, Any]]: ...                              # line 339
    async def neighbors(self, concept_id: str, rel: Optional[str] = None,
        direction: str = "both") -> list[dict[str, Any]]: ...                      # line 343
    async def dump_pages(self) -> list[dict[str, Any]]: ...                        # line 352
    async def dump_edges(self) -> list[dict[str, Any]]: ...                        # line 355
    async def stats(self) -> dict[str, Any]: ...                                   # line 358
    # Lint methods
    async def orphan_sources(self) -> list[str]: ...                               # line 362
    async def broken_edges(self) -> list[dict[str, Any]]: ...                      # line 365
    async def missing_bodies(self) -> list[str]: ...                               # line 368

class WikiPageRecord(BaseModel):  # line 205
    concept_id: str = Field(..., min_length=1)   # line 224
    node_id: Optional[str] = None                # line 225
    title: str = ""                              # line 226
    category: str = "concept"                    # line 227
    summary: str = ""                            # line 228
    body: str = ""                               # line 229
    source_id: Optional[str] = None              # line 230
    token_count: int = Field(default=0, ge=0)    # line 231
    origin: str = "ingest"                       # line 232
    asserted_by: Optional[str] = None            # line 233

def rank_by_cosine(embedding: list[float],
    candidates: list[tuple[dict[str, Any], list[float]]],
    limit: int = 10) -> list[dict[str, Any]]: ...                                  # line 236

def estimate_tokens(text: str) -> int: ...                                         # line 153
```

```python
# Reference pattern: packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py
class OntologyGraphStore:
    def __init__(self, arango_client: Any = None) -> None: ...          # line 49
    async def initialize_tenant(self, ctx: TenantContext) -> None: ...  # line 71
    async def upsert_nodes(self, ctx, collection, nodes,
        key_field) -> UpsertResult: ...                                 # line 225
    async def create_edges(self, ctx, edge_collection, edges) -> int: ...  # line 312

# Reference pattern: InMemoryWikiStore constructor
# packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py
class InMemoryWikiStore(BaseWikiStore):  # line 71
    def __init__(self, bundle_dir: str | Path, wiki_name: str = "") -> None: ...  # line 86
```

### Does NOT Exist

- ~~`BaseWikiStore.initialize()`~~ — no `initialize` method on the ABC
- ~~`BaseWikiStore.close()`~~ — no `close` method on the ABC
- ~~`parrot.knowledge.wiki.arango_store`~~ — does not exist yet; this task creates it
- ~~`OntologyGraphStore.fulltext_search()`~~ — OntologyGraphStore has no FTS
- ~~Any ArangoSearch views in the knowledge layer~~ — none exist yet

---

## Implementation Notes

### Pattern to Follow

Follow the same constructor pattern as `SQLiteWikiStore` and `InMemoryWikiStore`:

```python
class ArangoDBWikiStore(BaseWikiStore):
    def __init__(
        self,
        arango_params: dict[str, Any],
        database: str = "",
        wiki_name: str = "",
        text_analyzer: str = "text_en",
    ) -> None:
        self._params = arango_params
        self._database = database or f"wiki_{wiki_name or 'codebase'}"
        self._wiki_name = wiki_name
        self._text_analyzer = text_analyzer
        self._db: Optional[AsyncDB] = None
        self._initialized = False
        self.logger = logging.getLogger(__name__)

    async def initialize(self) -> None:
        """Connect, create database/collections/view if needed."""
        self._db = AsyncDB("arangodb", params={**self._params, "database": self._database})
        await self._db.connection()
        # create collections + ArangoSearch view
        ...
```

For AQL UPSERT pattern, follow `OntologyGraphStore.upsert_nodes()`:
```
UPSERT {_key: @key} INSERT @doc UPDATE @doc IN @@collection
```

For ArangoSearch view creation, use asyncdb's driver method:
```python
await self._db.create_arangosearch_view(
    f"{self._wiki_name}_pages_view",
    links={"wiki_pages": {
        "analyzers": [self._text_analyzer],
        "fields": {"title": {}, "summary": {}, "body": {}},
    }},
)
```

For BM25 full-text search:
```aql
FOR doc IN {view_name}
    SEARCH ANALYZER(doc.title IN TOKENS(@query, @analyzer) OR
                    doc.summary IN TOKENS(@query, @analyzer) OR
                    doc.body IN TOKENS(@query, @analyzer), @analyzer)
    SORT BM25(doc) DESC
    LIMIT @limit
    RETURN {concept_id: doc.concept_id, title: doc.title, ...}
```

### Key Constraints

- All methods are async
- `__init__` is sync — connection happens in `initialize()`
- Lazy init pattern: each public method should call `await self._ensure_init()`
- Edge `_from`/`_to` must be fully qualified: `"wiki_pages/<concept_id>"`
- Use `_key` field as the document key (set to `concept_id` for pages)
- ArangoSearch view name: `{wiki_name}_pages_view`

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` — BaseWikiStore ABC + SQLiteWikiStore reference
- `packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py` — InMemoryWikiStore reference
- `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` — ArangoDB connection + UPSERT patterns
- `packages/ai-parrot-embeddings/src/parrot/stores/arango.py` — ArangoSearch view creation patterns

---

## Acceptance Criteria

- [ ] `ArangoDBWikiStore` inherits `BaseWikiStore`
- [ ] All 15 abstract methods implemented
- [ ] `initialize()` creates database, 5 collections, and ArangoSearch view
- [ ] `close()` closes the asyncdb connection
- [ ] `search_fts()` returns BM25-ranked results via ArangoSearch
- [ ] `search_vector()` returns cosine-ranked results via `rank_by_cosine()`
- [ ] `neighbors()` traverses edges with direction filtering
- [ ] `replace_source_slice()` atomically deletes old pages + re-inserts
- [ ] All unit tests pass: `pytest tests/knowledge/wiki/test_arango_store.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py`

---

## Test Specification

```python
# tests/knowledge/wiki/test_arango_store.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore
from parrot.knowledge.wiki.store import WikiPageRecord


@pytest.fixture
def arango_params():
    return {"host": "127.0.0.1", "port": 8529, "username": "root", "password": ""}


@pytest.fixture
def store(arango_params):
    return ArangoDBWikiStore(arango_params, wiki_name="test")


class TestArangoDBWikiStore:
    def test_init(self, store):
        assert store._wiki_name == "test"
        assert store._database == "wiki_test"
        assert not store._initialized

    @pytest.mark.asyncio
    async def test_upsert_pages(self, store):
        # mock asyncdb, verify AQL UPSERT called
        ...

    @pytest.mark.asyncio
    async def test_search_fts(self, store):
        # mock ArangoSearch query, verify BM25 ranking
        ...

    @pytest.mark.asyncio
    async def test_search_vector(self, store):
        # mock embeddings fetch, verify rank_by_cosine called
        ...

    @pytest.mark.asyncio
    async def test_neighbors(self, store):
        # mock edge traversal, verify direction filtering
        ...

    @pytest.mark.asyncio
    async def test_stats(self, store):
        # mock collection counts
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/wikitoolkit-arangodb-backend.spec.md`
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm all imports and signatures
4. **Study the reference implementations**: `SQLiteWikiStore` for method semantics,
   `InMemoryWikiStore` for a clean non-SQLite implementation, `OntologyGraphStore`
   for ArangoDB patterns
5. **Implement** the store class with all 15 methods
6. **Test** with mocked asyncdb
7. **Move this file** to `tasks/completed/` and update the index

---

## Completion Note

*(Agent fills this in when done)*
