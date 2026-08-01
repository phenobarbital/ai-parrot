---
type: feature
base_branch: dev
reuse_feature_id: FEAT-400
---

# Feature Specification: WikiToolkit ArangoDB Backend

**Feature ID**: FEAT-400
**Date**: 2026-08-01
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.next

---

## 1. Motivation & Business Requirements

### Problem Statement

The LLM Wiki retrieval plane (`WikiToolkit`) is locked to a single-file
SQLite database per repository. This works well for single-developer,
single-machine workflows but prevents:

- **Shared knowledge graphs**: multiple repos/agents pointing at the same
  wiki instance on a centralized ArangoDB server.
- **Server-hosted wikis**: a production ArangoDB deployment that persists
  across environments (CI, staging, dev machines) without syncing `.db`
  files.
- **Graph-native queries**: ArangoDB's graph traversals and ArangoSearch
  views offer richer querying than SQLite FTS5 for cross-repository
  knowledge retrieval.

The `BaseWikiStore` abstraction already exists with 15 abstract methods and
two working backends (`SQLiteWikiStore`, `InMemoryWikiStore`), proving the
contract is backend-agnostic. The `asyncdb` driver provides all needed
ArangoSearch methods (`fulltext_search`, `vector_search`, `hybrid_search`,
`create_arangosearch_view`). This spec defines the third backend.

### Goals

- G1: A new `ArangoDBWikiStore(BaseWikiStore)` that implements all 15
  abstract methods via AQL and ArangoSearch views.
- G2: `WikiProjectConfig` (`.parrot/wiki.json`) and `WikiConfig` (runtime)
  accept `backend: "arangodb"` with connection fields.
- G3: `SourceCollectionManager` stores source metadata in an ArangoDB
  collection (`wiki_sources`) when the backend is `"arangodb"`.
- G4: The CLI (`wikitoolkit`) supports `--backend arangodb` for all
  read commands and the `build` command.
- G5: Default backend remains `"sqlite"` — zero config change for existing
  users.

### Non-Goals (explicitly out of scope)

- SQLite-to-ArangoDB migration tooling (future feature).
- ArangoDB cluster/replication configuration (operator responsibility).
- Multi-tenant wiki isolation within one ArangoDB database.
- Native ArangoDB vector index (`APPROX_NEAR`) — use the existing
  `rank_by_cosine()` brute-force approach initially.
- Commit/audit/revert protocol for wiki writes (not part of `BaseWikiStore`
  contract).
- A generic "remote store" abstraction supporting Postgres/MongoDB — this
  is ArangoDB-specific. Rejected during proposal to keep scope bounded.

---

## 2. Architectural Design

### Overview

Add a third `BaseWikiStore` backend backed by ArangoDB, using the `asyncdb`
library's ArangoDB driver. The wiki's pages, edges, embeddings, sources, and
metadata each map to an ArangoDB document collection (prefixed `wiki_`) in
a configurable database (default: `wiki_{wiki_name}`). An ArangoSearch view
provides BM25 full-text search over page content, and cosine-similarity
vector search uses the shared `rank_by_cosine()` helper (or optionally
ArangoSearch's vector capabilities).

Connection credentials come from environment variables following the
established `ARANGODB_*` pattern via navconfig, never hardcoded in
`wiki.json`. The database name is configurable in `wiki.json`, defaulting
to `wiki_{wiki_name}` for isolation from the ontology database.

The `SourceCollectionManager` gains an `"arangodb"` backend that stores
source metadata in a `wiki_sources` collection in the same database, giving
full parity with the SQLite path (no local filesystem dependency for a
centralized wiki).

### Component Diagram

```
.parrot/wiki.json (backend: "arangodb")
         │
         ▼
WikiProjectConfig ──→ create_wiki_store() ──→ ArangoDBWikiStore
         │                                          │
         │                                          ▼
         │                                    AsyncDB("arangodb")
         │                                          │
         ▼                                          ▼
LLMWikiToolkit ──→ SourceCollectionManager    ArangoDB Server
                   (backend="arangodb")       ┌─────────────────┐
                          │                   │ wiki_{name} DB   │
                          ▼                   │ ├─ wiki_pages    │
                   wiki_sources coll ────────►│ ├─ wiki_edges    │
                                              │ ├─ wiki_sources  │
WikiCombinedSearch ──→ store.search_fts() ──►│ ├─ wiki_embeddings│
                       store.search_vector()  │ ├─ wiki_meta     │
                                              │ └─ pages_view    │
WikiIngestOrchestrator ──→ store.replace_     │   (ArangoSearch) │
                           source_slice()     └─────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BaseWikiStore` | implements | New class implements 15 abstract methods |
| `create_wiki_store()` | extends | New `elif backend == "arangodb"` branch |
| `WikiProjectConfig` | extends | Add `"arangodb"` to `backend` Literal + connection fields |
| `WikiConfig` | extends | Add `"arangodb"` to `storage_backend` Literal |
| `SourceCollectionManager` | extends | Add `"arangodb"` backend option |
| `LLMWikiToolkit.__init__` | modifies | Add wiring for arangodb store + sources |
| `cli.py` | modifies | Backend option routing for arangodb |
| `WikiCombinedSearch` | type fix only | `WikiStore` → `BaseWikiStore` annotation |
| `WikiIngestOrchestrator` | type fix only | Same annotation fix |
| `asyncdb.AsyncDB` | uses | Existing async ArangoDB driver |
| `OntologyGraphStore` | reference pattern | Connection + UPSERT patterns |
| `ArangoDBStore` (embeddings) | reference pattern | ArangoSearch view creation patterns |

### Data Models

```python
# ArangoDB collection schemas (document structure)

# wiki_pages collection
{
    "_key": "<concept_id>",
    "concept_id": str,
    "node_id": Optional[str],
    "title": str,
    "category": str,        # default "concept"
    "summary": str,
    "body": str,
    "source_id": Optional[str],
    "token_count": int,
    "origin": str,           # "ingest" | "authored" | "memory"
    "asserted_by": Optional[str],
    "created_at": str,       # ISO-8601
    "updated_at": str,       # ISO-8601
}

# wiki_edges collection
{
    "_key": "<src>__<dst>__<rel>",   # deterministic composite key
    "_from": "wiki_pages/<src>",
    "_to": "wiki_pages/<dst>",
    "src": str,
    "dst": str,
    "rel": str,              # default "references"
    "provenance": str,       # default "extracted"
}

# wiki_embeddings collection
{
    "_key": "<concept_id>",
    "concept_id": str,
    "vector": list[float],   # stored as native JSON array
    "model": str,
}

# wiki_sources collection
{
    "_key": "<source_id>",
    "source_id": str,
    "source_uri": str,
    "file_hash": str,
    "mtime": float,
    "ingested_at": str,
    "pages_generated": list[str],
    "status": str,
}

# wiki_meta collection
{
    "_key": "<key>",
    "key": str,
    "value": str,
}
```

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py

class ArangoDBWikiStore(BaseWikiStore):
    """ArangoDB-backed wiki retrieval plane.

    Uses asyncdb's ArangoDB driver for document CRUD and ArangoSearch
    views for BM25 full-text search. Vector search uses the shared
    rank_by_cosine() helper over embeddings fetched from the
    wiki_embeddings collection.
    """

    def __init__(
        self,
        arango_params: dict[str, Any],
        database: str = "",
        wiki_name: str = "",
        text_analyzer: str = "text_en",
    ) -> None: ...

    async def initialize(self) -> None:
        """Connect to ArangoDB, create database/collections/views if needed."""
        ...

    async def close(self) -> None:
        """Close the ArangoDB connection."""
        ...

    # ... all 15 BaseWikiStore abstract methods ...
```

```python
# Extended config fields on WikiProjectConfig (project.py)

class WikiProjectConfig(BaseModel):
    backend: Literal["sqlite", "memory", "arangodb"] = "sqlite"
    arango_database: Optional[str] = None    # default: wiki_{wiki_name}
    arango_credentials_env: str = "ARANGODB"  # env var prefix
    arango_text_analyzer: str = "text_en"     # ArangoSearch analyzer
```

---

## 3. Module Breakdown

### Module 1: ArangoDBWikiStore
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py`
- **Responsibility**: Implement all 15 `BaseWikiStore` abstract methods
  against ArangoDB collections + ArangoSearch views. Handle connection
  lifecycle, collection/view creation, AQL UPSERT, FTS via BM25, vector
  search via `rank_by_cosine()`.
- **Depends on**: `asyncdb`, `BaseWikiStore`, `WikiPageRecord`,
  `rank_by_cosine()`, `estimate_tokens()`

### Module 2: Config Extension
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` +
  `packages/ai-parrot/src/parrot/knowledge/wiki/models.py`
- **Responsibility**: Extend `WikiProjectConfig.backend` and
  `WikiConfig.storage_backend` Literals to include `"arangodb"`. Add
  optional ArangoDB connection fields to `WikiProjectConfig`. Add credential
  resolution helper.
- **Depends on**: none (pure model changes)

### Module 3: Factory + Wiring
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (factory),
  `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` (wiring),
  `packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py` (exports)
- **Responsibility**: Extend `create_wiki_store()` with `"arangodb"` branch.
  Wire `LLMWikiToolkit.__init__` to create `ArangoDBWikiStore` and
  `ArangoDBSourceManager` when backend is `"arangodb"`. Export new class.
- **Depends on**: Module 1, Module 2

### Module 4: SourceCollectionManager ArangoDB Backend
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py`
- **Responsibility**: Add `"arangodb"` backend to `SourceCollectionManager`
  that stores source metadata in a `wiki_sources` collection. Provide async
  methods wrapping the existing sync interface.
- **Depends on**: Module 1 (shares the ArangoDB connection)

### Module 5: CLI Integration
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- **Responsibility**: Extend `--backend` choice to include `"arangodb"`.
  Update `_resolve_read_store()` and `_open_sources()` to handle the new
  backend. Wrap async ArangoDB operations in `asyncio.run()` for CLI context.
- **Depends on**: Module 1, Module 2, Module 3

### Module 6: Type Annotation Fixes
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/search.py`,
  `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py`
- **Responsibility**: Change `WikiStore` type annotations to `BaseWikiStore`
  in `WikiCombinedSearch.__init__` and `WikiIngestOrchestrator.__init__`.
- **Depends on**: none

### Module 7: Tests
- **Path**: `tests/knowledge/wiki/test_arango_store.py`,
  `tests/knowledge/wiki/test_sources_arango.py`
- **Responsibility**: Unit tests for `ArangoDBWikiStore` (mocked asyncdb) +
  integration tests (real ArangoDB instance). Test all 15 store methods +
  source tracking. Verify round-trip: build → query → ingest → search.
- **Depends on**: Module 1, Module 4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_arango_store_init` | 1 | Validates store creation with params |
| `test_arango_store_initialize_creates_collections` | 1 | Verifies all 5 collections + view created |
| `test_arango_store_upsert_pages` | 1 | Upsert pages, verify count returned |
| `test_arango_store_add_edges` | 1 | Add edges with 3-tuple and 4-tuple variants |
| `test_arango_store_replace_source_slice` | 1 | Atomic delete + re-insert for a source |
| `test_arango_store_delete_page` | 1 | Delete page and its edges/embeddings |
| `test_arango_store_upsert_embedding` | 1 | Store and retrieve embedding vector |
| `test_arango_store_get_page` | 1 | Fetch by concept_id and node_id fallback |
| `test_arango_store_list_pages` | 1 | Filter by category, origin, limit |
| `test_arango_store_search_fts` | 1 | BM25 search returns scored results |
| `test_arango_store_search_vector` | 1 | Cosine search returns scored results |
| `test_arango_store_neighbors` | 1 | Edge traversal with direction filter |
| `test_arango_store_dump_pages` | 1 | Bulk export all pages |
| `test_arango_store_dump_edges` | 1 | Bulk export all edges |
| `test_arango_store_stats` | 1 | Aggregate counters correct |
| `test_arango_store_orphan_sources` | 1 | Lint: sources with no pages |
| `test_arango_store_broken_edges` | 1 | Lint: edges to nonexistent pages |
| `test_arango_store_missing_bodies` | 1 | Lint: pages with empty body |
| `test_config_arangodb_backend` | 2 | WikiProjectConfig accepts "arangodb" |
| `test_config_arango_fields` | 2 | Optional arango_* fields parse correctly |
| `test_config_defaults_unchanged` | 2 | Default backend still "sqlite" |
| `test_factory_arangodb_branch` | 3 | `create_wiki_store(backend="arangodb")` returns ArangoDBWikiStore |
| `test_sources_arango_add_source` | 4 | Source metadata stored in ArangoDB |
| `test_sources_arango_is_stale` | 4 | Staleness detection via ArangoDB lookup |
| `test_sources_arango_mark_ingested` | 4 | Update source after ingest |
| `test_type_annotations_basewikistore` | 6 | search.py and ingest.py accept any BaseWikiStore |

### Integration Tests

| Test | Description |
|---|---|
| `test_arango_build_and_query` | Full pipeline: build wiki from test files → query → verify results |
| `test_arango_ingest_roundtrip` | Ingest sources → search FTS → search vector → verify |
| `test_arango_cli_backend` | CLI `wikitoolkit query` with `--backend arangodb` |

### Test Data / Fixtures

```python
@pytest.fixture
def arango_params():
    """ArangoDB connection params for test instance."""
    return {
        "host": os.environ.get("TEST_ARANGODB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("TEST_ARANGODB_PORT", "8529")),
        "username": os.environ.get("TEST_ARANGODB_USERNAME", "root"),
        "password": os.environ.get("TEST_ARANGODB_PASSWORD", ""),
        "database": f"test_wiki_{uuid.uuid4().hex[:8]}",
    }

@pytest.fixture
async def arango_store(arango_params):
    """Initialized ArangoDBWikiStore for testing."""
    store = ArangoDBWikiStore(arango_params, wiki_name="test")
    await store.initialize()
    yield store
    await store.close()
    # cleanup: drop test database
```

---

## 5. Acceptance Criteria

- [x] Default backend remains `"sqlite"` — existing users unaffected
- [ ] `ArangoDBWikiStore` implements all 15 `BaseWikiStore` abstract methods
- [ ] `WikiProjectConfig.backend` accepts `"arangodb"` with optional
  `arango_database`, `arango_credentials_env`, `arango_text_analyzer` fields
- [ ] `WikiConfig.storage_backend` accepts `"arangodb"`
- [ ] `create_wiki_store(backend="arangodb")` returns a working
  `ArangoDBWikiStore` instance
- [ ] `SourceCollectionManager` supports `backend="arangodb"` storing
  metadata in a `wiki_sources` collection
- [ ] `wikitoolkit build --backend arangodb` builds a wiki into ArangoDB
- [ ] `wikitoolkit query` works against an ArangoDB-backed wiki
- [ ] Credentials resolved from `ARANGODB_*` env vars — never hardcoded
- [ ] ArangoSearch view created with configurable text analyzer
- [ ] Database defaults to `wiki_{wiki_name}`, overridable via config
- [ ] All unit tests pass (`pytest tests/knowledge/wiki/ -v`)
- [ ] Integration tests pass with a real ArangoDB instance
- [ ] Type annotations in `search.py` and `ingest.py` use `BaseWikiStore`
- [ ] No breaking changes to existing `SQLiteWikiStore` or `InMemoryWikiStore`
- [ ] `ArangoDBWikiStore` exported from `parrot.knowledge.wiki`

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# Store abstraction
from parrot.knowledge.wiki.store import BaseWikiStore       # verified: store.py:279
from parrot.knowledge.wiki.store import WikiPageRecord       # verified: store.py:205
from parrot.knowledge.wiki.store import create_wiki_store    # verified: store.py:1197
from parrot.knowledge.wiki.store import rank_by_cosine       # verified: store.py:236
from parrot.knowledge.wiki.store import estimate_tokens      # verified: store.py:153
from parrot.knowledge.wiki.store import WikiStore            # verified: store.py:1194 (alias for SQLiteWikiStore)
from parrot.knowledge.wiki.store import SQLiteWikiStore      # verified: store.py:431

# File store
from parrot.knowledge.wiki.file_store import InMemoryWikiStore  # verified: file_store.py:71

# Config
from parrot.knowledge.wiki.project import WikiProjectConfig  # verified: project.py:121
from parrot.knowledge.wiki.project import load_project_config  # verified: project.py:203
from parrot.knowledge.wiki.project import save_project_config  # verified: project.py:230
from parrot.knowledge.wiki.models import WikiConfig          # verified: models.py (class def in content)

# Sources
from parrot.knowledge.wiki.sources import SourceCollectionManager  # verified: sources.py:64

# Consumers
from parrot.knowledge.wiki.search import WikiCombinedSearch  # verified: search.py:47
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator  # verified: ingest.py:89

# ArangoDB (existing)
from asyncdb import AsyncDB  # verified: used in ontology/graph_store.py, loader.py
```

### Existing Class Signatures

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
    # Concrete method
    async def rebuild_from_tree(self, tree: dict[str, Any],
        content_loader: Optional[Callable[[str], Optional[str]]] = None,
        source_id: Optional[str] = None) -> dict[str, Any]: ...                    # line 372

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

def create_wiki_store(storage_dir: str | Path, wiki_name: str = "",
    backend: str = "sqlite") -> BaseWikiStore: ...                                 # line 1197

def rank_by_cosine(embedding: list[float],
    candidates: list[tuple[dict[str, Any], list[float]]],
    limit: int = 10) -> list[dict[str, Any]]: ...                                  # line 236

WikiStore = SQLiteWikiStore  # line 1194
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py

class WikiProjectConfig(BaseModel):  # line 121
    wiki_name: str = Field(default="codebase")                          # line 139
    storage_dir: str = Field(default=".parrot/wiki")                    # line 140
    backend: Literal["sqlite", "memory"] = Field(default="sqlite")     # line 141
    include_suffixes: list[str] = Field(default_factory=list)           # line 142
    exclude_dirs: list[str] = Field(default_factory=list)               # line 143
    body_max_chars: int = Field(default=16_000, ge=1_000)               # line 144
    max_file_kb: int = Field(default=512, ge=1)                         # line 145
    claude: ClaudeIntegrationConfig = Field(...)                        # line 146
    sync_graph: bool = Field(default=False)                             # line 149
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/models.py

class WikiConfig(BaseModel):
    wiki_name: str = Field(...)
    storage_dir: Path = Field(...)
    storage_backend: Literal["sqlite", "memory"] = Field(default="sqlite")
    # ... other fields (search_weights, model, sync_graph, etc.)
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py

class SourceCollectionManager:
    def __init__(self, sources_dir: Path, db_path: Optional[Path] = None,
        backend: Literal["sqlite", "json"] = "sqlite") -> None: ...     # line 64
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py

class LLMWikiToolkit:
    def __init__(self, pageindex_toolkit: Any, graphindex_toolkit: Any,
        okf_toolkit: Any, config: WikiConfig, agent_id: str = "agent",
        **kwargs: Any) -> None: ...                                     # line 75
    # Store creation: lines 105-109
    # Sources creation: lines 110-118 (if/else on config.storage_backend)
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py

def _resolve_read_store(path_: Optional[str], store_opt: Optional[str],
    backend_opt: Optional[str]) -> BaseWikiStore: ...                   # line 160

def _open_sources(root: Path,
    config: WikiProjectConfig) -> SourceCollectionManager: ...          # line 115

# build command: --backend option at lines 618-623
# click.Choice(["sqlite", "memory"]) — needs "arangodb" added
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/search.py

class WikiCombinedSearch:
    def __init__(self, ..., store: Optional[WikiStore] = None, ...) -> None: ...  # line 47
    # ↑ WikiStore should be BaseWikiStore
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py

class WikiIngestOrchestrator:
    def __init__(self, ..., store: Optional[WikiStore] = None, ...) -> None: ...  # line 89
    # ↑ WikiStore should be BaseWikiStore
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py

class InMemoryWikiStore(BaseWikiStore):  # line 71
    def __init__(self, bundle_dir: str | Path, wiki_name: str = "") -> None: ...  # line 86
```

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py (reference pattern)

class OntologyGraphStore:
    def __init__(self, arango_client: Any = None) -> None: ...          # line 49
    async def initialize_tenant(self, ctx: TenantContext) -> None: ...  # line 71
    async def upsert_nodes(self, ctx, collection, nodes, key_field) -> UpsertResult: ...  # line 225
    async def create_edges(self, ctx, edge_collection, edges) -> int: ...  # line 312
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ArangoDBWikiStore` | `BaseWikiStore` | inheritance | `store.py:279` |
| `ArangoDBWikiStore` | `AsyncDB("arangodb")` | composition | `asyncdb` driver |
| `ArangoDBWikiStore` | `rank_by_cosine()` | function call | `store.py:236` |
| `create_wiki_store()` | `ArangoDBWikiStore` | factory branch | `store.py:1197` |
| `WikiProjectConfig` | `ArangoDBWikiStore` | config → factory | `project.py:141` |
| `WikiConfig` | `LLMWikiToolkit` | runtime config | `models.py` |
| `SourceCollectionManager` | `wiki_sources` coll | ArangoDB backend | `sources.py:64` |
| `LLMWikiToolkit.__init__` | `ArangoDBWikiStore` | store creation | `toolkit.py:105` |
| `cli.py` build cmd | `ArangoDBWikiStore` | `--backend arangodb` | `cli.py:618` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.knowledge.wiki.arango_store`~~ — does not exist yet; Module 1 creates it
- ~~`ArangoDBWikiStore`~~ — does not exist yet
- ~~`SourceCollectionManager(backend="arangodb")`~~ — not accepted yet; Module 4 adds it
- ~~`WikiProjectConfig.arango_database`~~ — field does not exist yet; Module 2 adds it
- ~~`WikiProjectConfig.arango_credentials_env`~~ — does not exist yet
- ~~`WikiProjectConfig.arango_text_analyzer`~~ — does not exist yet
- ~~`BaseWikiStore.initialize()`~~ — no `initialize` method on the ABC; `ArangoDBWikiStore` adds its own
- ~~`BaseWikiStore.close()`~~ — no `close` method on the ABC; `ArangoDBWikiStore` adds its own
- ~~`OntologyGraphStore.fulltext_search()`~~ — OntologyGraphStore has no FTS; asyncdb driver does
- ~~Any ArangoSearch views in the knowledge layer~~ — none exist; this feature creates the first

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **asyncdb connection**: `AsyncDB("arangodb", params={...})` +
  `await db.connection()` — same as `OntologyGraphStore` in
  `graphindex/loader.py:296-313`.
- **ArangoSearch view creation**: `db.create_arangosearch_view(view_name,
  links={...})` — same pattern as `ArangoDBStore` in
  `ai-parrot-embeddings/stores/arango.py`.
- **AQL UPSERT**: `UPSERT {_key: @key} INSERT @doc UPDATE @doc IN @@coll`
  with batch + individual fallback — same as
  `OntologyGraphStore.upsert_nodes()` at `graph_store.py:225`.
- **BM25 full-text search**: `ANALYZER(doc.field IN TOKENS(@query,
  @analyzer), @analyzer)` + `SORT BM25(doc) DESC` — pattern from asyncdb's
  `fulltext_search()` method.
- **Credential resolution**: `ARANGODB_HOST`, `ARANGODB_PORT`,
  `ARANGODB_USERNAME`, `ARANGODB_PASSWORD` env vars via navconfig or
  `os.environ` — same as `graphindex/loader.py:315-369`.
- **Store constructor pattern**: `(first_positional: str | Path,
  wiki_name: str = "")` — match `SQLiteWikiStore.__init__` and
  `InMemoryWikiStore.__init__` signatures for consistency.

### Known Risks / Gotchas

- **Async/sync boundary**: `SourceCollectionManager`'s public API is
  synchronous. The ArangoDB backend must bridge this — either make the
  arango methods async and wrap calls in `asyncio.to_thread` (from sync
  callers) or run a private event loop. The CLI already wraps async store
  calls via `asyncio.run()`, so the pattern exists.
- **ArangoSearch analyzer choice**: SQLite FTS5 uses the `unicode61`
  tokenizer (language-agnostic). ArangoSearch has language-specific
  analyzers (`text_en`, `text_es`, etc.). Making this configurable via
  `arango_text_analyzer` prevents locking to one language.
- **Edge `_from`/`_to` resolution**: ArangoDB edge collections require
  fully-qualified `_from`/`_to` references (`collection/key`). The wiki's
  edge model uses bare `src`/`dst` concept IDs. The store must prefix them
  with `wiki_pages/` — but if `dst` targets a source (not a page), it
  should use `wiki_sources/`. Check the `neighbors()` and `broken_edges()`
  implementations carefully.
- **Connection lifecycle**: `create_wiki_store()` is synchronous.
  `ArangoDBWikiStore.__init__` cannot `await`. The connection + collection
  creation must happen lazily on first use or via an explicit
  `await store.initialize()` call. The factory should document this.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncdb[arangodb]` | `>=2.11.6` | ArangoDB async driver (already a dependency) |
| `navconfig` | existing | Environment variable resolution (already used) |

---

## 8. Open Questions

### Resolved (carried from proposal)

- [x] **Should the ArangoDB wiki use a dedicated database or share the
  ontology database?** — *Resolved in proposal*: Configurable. Default to
  `wiki_{wiki_name}`, overridable via `arango_database` config field.
- [x] **How should SourceCollectionManager handle the ArangoDB backend?**
  — *Resolved in proposal*: ArangoDB collection (`wiki_sources`) in the same
  database. Full parity, no local files needed.

### Unresolved (defer to implementation)

- [ ] **Which ArangoSearch text analyzer should be the default?** —
  *Owner: implementer*. Likely `text_en` (matches `ArangoDBStore`
  convention), configurable via `arango_text_analyzer`. Can be decided
  during Module 1 implementation.

---

## Worktree Strategy

- **Isolation unit**: per-spec (all 7 modules sequential in one worktree)
- **Rationale**: Modules have strict dependency chain (1→2→3→4→5, 6
  independent, 7 depends on all). No parallelism benefit.
- **Cross-feature dependencies**: none — `BaseWikiStore` contract is stable.

```bash
git worktree add -b feat-400-wikitoolkit-arangodb-backend \
  .claude/worktrees/feat-400-wikitoolkit-arangodb-backend HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-01 | Jesus Lara / Claude Opus 4.6 | Initial draft from FEAT-400 proposal |
