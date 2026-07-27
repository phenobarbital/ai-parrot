---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: MultiStoreSearch Toolkit with PageIndex, GraphIndex & ParrotWiki Origins

**Feature ID**: FEAT-379
**Date**: 2026-07-27
**Author**: Jesus
**Status**: draft
**Target version**: next minor
**Brainstorm**: `sdd/proposals/multistoresearchtool-parrotwiki.brainstorm.md`

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

`MultiStoreSearchTool` (`packages/ai-parrot-tools/src/parrot_tools/multistoresearch.py`)
searches only **vector-based** origins (pgVector, FAISS, ArangoDB) via
`similarity_search`, merges with BM25 reranking, and returns a flat top-k list.
The codebase has grown three non-vector retrieval planes that agents cannot
reach through multi-search:

- **PageIndex** (`parrot/knowledge/pageindex/`) — vectorless, tree-based
  reasoning RAG (LLM tree-walk, vector-walk, and hybrid modes).
- **GraphIndex** (`parrot/knowledge/graphindex/`) — 4-phase graph retrieval
  (seed → expand → community annotation → assembly).
- **ParrotWiki / LLM-Wiki** (`parrot/knowledge/wiki/`) — `WikiStore` SQLite
  retrieval plane with native FTS + vector search.

Agents configured for multi-search context retrieval get only the vector view
of knowledge. Additionally the component is a single `AbstractTool` with no
room for sibling operations (batch search, full-text search, origin
introspection) without schema bloat.

Affected: agent developers wiring RAG context; end users of agents whose
answers miss knowledge living only in PageIndex/GraphIndex/wiki; the FEAT-111
`StoreRouter`, whose FAN_OUT policy delegates to this tool.

### Goals

- Convert `MultiStoreSearchTool` into `MultiStoreSearchToolkit(AbstractToolkit)`
  as a **clean break** (decision: no deprecation shim; all call sites migrate
  in-feature).
- Add three new search origins — PageIndex, GraphIndex, ParrotWiki — beside
  the existing vector-store origins, each individually enable/disable-able via
  a `SearchOrigin` **adapter registry** (decision).
- Expose four agent-facing tools: `store_search`, `batch_search`, `fts_search`,
  `list_search_origins` (decision; `multi_store_search` name retires).
- Every search response contains **both** grouped-by-origin sections (native
  ranking + an origin explanation the LLM can read) **and** a merged
  BM25-reranked top-k block (decision).
- `batch_search` fans N queries × M origins through a single `asyncio.gather`
  (decision: pure async; no `asyncio.to_thread`).
- Per-origin failures and timeouts degrade to in-payload notes; they never
  fail the whole call. Default per-origin timeout **30 s**, overridable per
  adapter (decision).
- Decouple core from `parrot_tools`: `StoreRouter` FAN_OUT types against a
  narrow protocol defined in core, not the toolkit class (decision).

### Non-Goals (explicitly out of scope)

- Postgres tsvector/FTS support on `PgVectorStore` — `fts_search` covers only
  origins that are FTS-capable today (wiki, Arango, GraphIndex-SQLite);
  non-capable origins are skipped with a note (decision).
- Backwards-compatibility shim for `MultiStoreSearchTool` — rejected in
  brainstorm (clean break; see proposals/multistoresearchtool-parrotwiki.brainstorm.md).
- Extending the existing tool in place (brainstorm Option B) or building a
  façade over `WikiCombinedSearch` (brainstorm Option C) — rejected; the
  ParrotWiki adapter calls `WikiStore` directly (decision).
- Changes to the knowledge planes themselves (`parrot/knowledge/*` is consumed
  read-only).
- Cross-origin score normalization — origin scores are not comparable by
  construction; the merged block relies on BM25-over-content.

---

## 2. Architectural Design

### Overview

A new **`MultiStoreSearchToolkit`** (inherits `AbstractToolkit`,
`packages/ai-parrot/src/parrot/tools/toolkit.py:207`) owns an ordered registry
of **`SearchOrigin` adapters**. Each adapter wraps one backend and exposes a
uniform surface: `name`, `kind` (new `SearchOriginKind` enum in core —
decision: lives in `parrot/models/stores.py` beside `StoreType`, which stays
DB-only), `description` (the LLM-readable origin explanation),
`supports_fts`, `timeout` (default 30 s from the toolkit, overridable),
`async search(query, k)`, and optional `async fts_search(query, k)`.

Built-in adapters:

| Adapter | Backend | Notes |
|---|---|---|
| `VectorStoreOrigin` | any duck-typed `similarity_search(query, limit=...)` store (pgvector / FAISS / Arango) | same duck-typing as today; one adapter instance per store |
| `PageIndexOrigin` | PageIndex | retrieval `mode` config: `vector` (`FlatMatrixSearch.search`, sync — wrapped so it never blocks the loop) \| `hybrid` (`HybridPageIndexSearch.search`) \| `llm` (`PageIndexRetriever.search`, token-spending); **default `hybrid`** (decision) |
| `GraphIndexOrigin` | `GraphExpandedRetriever.search` | 4-phase graph retrieval result flattened to hits |
| `ParrotWikiOrigin` | `WikiStore.search_fts` / `search_vector` **directly** (decision — no `WikiCombinedSearch` delegation) | vector leg requires an async `embedder`; FTS leg is native |

Adapters normalize their backend's native result type (`SearchResult`,
`TreeSearchResult`, `GraphRetrievalResult`, wiki dict rows) into one Pydantic
hit model at the adapter boundary; the toolkit core stays type-clean.

The toolkit's public async methods become the agent tools automatically
(`AbstractToolkit` behavior — name = method name, description = docstring):

- **`store_search(query, k)`** — gathers `adapter.search()` for all enabled
  origins with `return_exceptions=True` + per-origin `asyncio.wait_for`;
  returns grouped sections (native order, origin explanation) + merged
  BM25-reranked top-k (dedup by ID then content hash, lifted from the current
  tool).
- **`batch_search(queries, k)`** — N queries × M origins in one
  `asyncio.gather`; per-query results in `store_search` shape.
- **`fts_search(query, k)`** — runs only on adapters with
  `supports_fts=True`; response notes which enabled origins were skipped and
  why.
- **`list_search_origins()`** — static configuration view: name, kind,
  description, FTS capability, key settings (e.g. PageIndex mode, timeout).

**Core decoupling**: core gains a narrow runtime-checkable protocol
(`MultiSearch`-style: `async search(query, k) -> list[dict]`) that
`StoreRouter._execute_fallback` and `AbstractBot.configure_store_router` type
against. The toolkit satisfies the protocol via `store_search` (or a thin
`search` alias excluded from tool generation via `exclude_tools`). Core never
imports `parrot_tools`, not even under `TYPE_CHECKING` (decision).

### Component Diagram

```
Agent ──tools──→ MultiStoreSearchToolkit (parrot_tools, AbstractToolkit)
                    │  store_search / batch_search / fts_search / list_search_origins
                    │
                    ├─→ VectorStoreOrigin(pgvector) ─→ store.similarity_search()
                    ├─→ VectorStoreOrigin(faiss)    ─→ store.similarity_search()
                    ├─→ VectorStoreOrigin(arango)   ─→ store.similarity_search() / fulltext_search()
                    ├─→ PageIndexOrigin(mode)       ─→ HybridPageIndexSearch | PageIndexRetriever | FlatMatrixSearch
                    ├─→ GraphIndexOrigin            ─→ GraphExpandedRetriever.search()
                    └─→ ParrotWikiOrigin            ─→ WikiStore.search_fts() / search_vector()

StoreRouter (core, FAN_OUT) ──→ MultiSearch protocol (core) ←─satisfies── MultiStoreSearchToolkit
AbstractBot.configure_store_router(multi_store_tool: MultiSearch)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot_tools/multistoresearch.py` | **replaced** | clean break: module becomes package `parrot_tools/multistoresearch/` (toolkit + adapters); old `MultiStoreSearchTool` deleted |
| `parrot_tools/__init__.py:119` | modifies | lazy-registry entry `"multi_store_search"` → new toolkit path (`multi_store_search_toolkit`) |
| `parrot/registry/routing/store_router.py:189,299-311` | modifies | FAN_OUT calls protocol `search()` instead of `MultiStoreSearchTool._execute()`; `TYPE_CHECKING` import of `parrot_tools` removed |
| `parrot/bots/abstract.py:117-129,577,2040-2066,3200` | modifies | `_multi_store_tool` retyped to the core protocol; guarded `parrot_tools` import removed |
| `parrot/models/stores.py` | extends | new `SearchOriginKind` enum + normalized hit/response models; `StoreType` untouched |
| `parrot/knowledge/{pageindex,graphindex,wiki}` | depends on | read-only consumption via adapters |
| `tests/integration/rag/test_store_router_integration.py` | modifies | fakes rebuilt against the protocol |

### Data Models

```python
# New — parrot/models/stores.py (core; names final at implementation)
class SearchOriginKind(Enum):
    """Kinds of multi-search origins. StoreType stays DB-store-only."""
    VECTOR = "vector"          # duck-typed similarity_search stores
    PAGEINDEX = "pageindex"
    GRAPHINDEX = "graphindex"
    WIKI = "wiki"

class OriginHit(BaseModel):
    """One normalized result from any origin."""
    id: Optional[str]
    content: str
    score: Optional[float]          # origin-native; NOT cross-origin comparable
    metadata: dict[str, Any]
    origin: str                     # adapter name, e.g. "pgvector", "wiki"
    origin_kind: SearchOriginKind
    native_rank: int                # 1-based position in the origin's own ranking

class OriginSection(BaseModel):
    """Grouped per-origin block of a search response."""
    origin: str
    origin_kind: SearchOriginKind
    description: str                # LLM-readable explanation of this origin
    status: str                     # "ok" | "error" | "timeout" | "skipped"
    note: Optional[str]             # error/timeout/skip explanation
    hits: list[OriginHit]           # native order preserved; may be empty

class MultiSearchResponse(BaseModel):
    """store_search / fts_search payload: grouped sections + merged top-k."""
    query: str
    sections: list[OriginSection]
    merged_top_k: list[OriginHit]   # BM25-reranked + deduped across origins
    notes: list[str]                # e.g. "score scales are origin-native"
```

### New Public Interfaces

```python
# Core protocol — new module (e.g. parrot/interfaces/search.py); exact home
# confirmed at implementation, MUST live in ai-parrot core, not parrot_tools.
@runtime_checkable
class MultiSearch(Protocol):
    async def search(self, query: str, k: Optional[int] = None, **kwargs) -> Any: ...

# parrot_tools/multistoresearch/ (package replacing the module)
class SearchOrigin(ABC):               # adapter contract
    name: str
    kind: SearchOriginKind
    description: str
    supports_fts: bool
    timeout: Optional[float]           # None → toolkit default (30.0)
    async def search(self, query: str, k: int) -> list[OriginHit]: ...
    async def fts_search(self, query: str, k: int) -> list[OriginHit]: ...  # only if supports_fts

class MultiStoreSearchToolkit(AbstractToolkit):
    def __init__(self, origins: list[SearchOrigin], k: int = 10,
                 k_per_origin: int = 20, default_timeout: float = 30.0,
                 bm25_weights: Optional[dict[str, float]] = None, **kwargs): ...
    async def store_search(self, query: str, k: Optional[int] = None) -> MultiSearchResponse: ...
    async def batch_search(self, queries: list[str], k: Optional[int] = None) -> list[MultiSearchResponse]: ...
    async def fts_search(self, query: str, k: Optional[int] = None) -> MultiSearchResponse: ...
    async def list_search_origins(self) -> list[dict[str, Any]]: ...
    # satisfies MultiSearch for StoreRouter FAN_OUT (alias excluded from tool generation)
```

---

## 3. Module Breakdown

> Modules map to Task Artifacts in Phase 2.

### Module 1: Core models — `SearchOriginKind` + normalized hit/response models
- **Path**: `packages/ai-parrot/src/parrot/models/stores.py` (+ `parrot/models/__init__.py` exports)
- **Responsibility**: `SearchOriginKind`, `OriginHit`, `OriginSection`, `MultiSearchResponse`. `StoreType` untouched.
- **Depends on**: nothing new.

### Module 2: Core `MultiSearch` protocol + StoreRouter/AbstractBot decoupling
- **Path**: new core module (e.g. `packages/ai-parrot/src/parrot/interfaces/search.py`), `parrot/registry/routing/store_router.py`, `parrot/bots/abstract.py`
- **Responsibility**: define the narrow protocol; retype `multistore_tool`/`_multi_store_tool`; FAN_OUT calls `protocol.search()`; remove `parrot_tools` imports from core.
- **Depends on**: Module 1.

### Module 3: `SearchOrigin` contract + `VectorStoreOrigin` adapter
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/` (new package: `origins/base.py`, `origins/vector.py`)
- **Responsibility**: adapter ABC (name/kind/description/supports_fts/timeout/search/fts_search) + duck-typed vector-store adapter (incl. Arango `fulltext_search` FTS leg); normalization of `SearchResult` → `OriginHit`.
- **Depends on**: Module 1.

### Module 4: `PageIndexOrigin` adapter
- **Path**: `parrot_tools/multistoresearch/origins/pageindex.py`
- **Responsibility**: mode dispatch `vector | hybrid | llm` (default `hybrid`); sync `FlatMatrixSearch.search` wrapped off the event loop; normalize node dicts → `OriginHit`.
- **Depends on**: Module 3.

### Module 5: `GraphIndexOrigin` adapter
- **Path**: `parrot_tools/multistoresearch/origins/graphindex.py`
- **Responsibility**: wrap `GraphExpandedRetriever.search(query, seed_top_k, ...)`; flatten `GraphRetrievalResult` → `OriginHit` list.
- **Depends on**: Module 3.

### Module 6: `ParrotWikiOrigin` adapter
- **Path**: `parrot_tools/multistoresearch/origins/wiki.py`
- **Responsibility**: `WikiStore.search_fts` (FTS + default lexical search) and `search_vector` (when an async embedder is configured); `supports_fts=True`.
- **Depends on**: Module 3.

### Module 7: `MultiStoreSearchToolkit` core
- **Path**: `parrot_tools/multistoresearch/toolkit.py` (+ package `__init__.py`)
- **Responsibility**: the four tools; per-origin `asyncio.wait_for` + `gather(return_exceptions=True)`; grouped sections + merged block; BM25 rerank + dedup lifted from the old tool; `MultiSearch`-satisfying alias via `exclude_tools`.
- **Depends on**: Modules 1, 3–6.

### Module 8: Clean-break migration & registry
- **Path**: `parrot_tools/__init__.py`, deletion of old `parrot_tools/multistoresearch.py`, `tests/integration/rag/test_store_router_integration.py`
- **Responsibility**: registry entry swap; delete `MultiStoreSearchTool`; migrate integration tests to protocol-based fakes; release-notes entry flagging the removal.
- **Depends on**: Modules 2, 7.

### Module 9: Documentation
- **Path**: `docs/` (toolkit guide + migration note)
- **Responsibility**: configuration examples for the four origin families, tool payload shape, score-comparability caveat.
- **Depends on**: Module 7.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_origin_kind_enum_and_models` | 1 | Enum values; `OriginHit`/`MultiSearchResponse` validation; `StoreType` unchanged |
| `test_multisearch_protocol_runtime_check` | 2 | Toolkit instance passes `isinstance(x, MultiSearch)`; a bare object does not |
| `test_store_router_fanout_uses_protocol` | 2 | FAN_OUT calls `search()` on any protocol-satisfying fake; no `parrot_tools` import in core modules |
| `test_vector_origin_normalizes_searchresult` | 3 | Duck-typed store fake → `OriginHit` with origin tag + native_rank |
| `test_vector_origin_error_isolated` | 3 | Store raising → empty hits + status="error" note |
| `test_pageindex_origin_mode_dispatch` | 4 | `vector`/`hybrid`/`llm` route to the right backend; default is `hybrid`; sync path doesn't block loop |
| `test_graphindex_origin_flattens_result` | 5 | `GraphRetrievalResult` fake → ordered `OriginHit` list |
| `test_wiki_origin_fts_and_vector` | 6 | `search_fts` rows normalized; vector leg only when embedder present; `supports_fts` True |
| `test_store_search_grouped_and_merged` | 7 | Response has one section per enabled origin (native order) + BM25-merged deduped top-k |
| `test_store_search_timeout_note` | 7 | Slow origin (`wait_for` expiry) → status="timeout", others unaffected |
| `test_batch_search_gather` | 7 | N queries → N responses; single-gather concurrency; empty list → empty result |
| `test_fts_search_skips_non_capable` | 7 | Non-FTS origins skipped with note; zero capable origins → notes-only response |
| `test_list_search_origins` | 7 | Static config view incl. PageIndex mode, timeouts, FTS capability |
| `test_no_origins_configured` | 7 | Structured "no origins configured" message, no exception |
| `test_registry_exposes_toolkit` | 8 | `parrot_tools` lazy registry resolves the new toolkit; old path gone |

### Integration Tests
| Test | Description |
|---|---|
| `test_store_router_integration` (updated) | FAN_OUT policy end-to-end with a protocol-satisfying toolkit fake |
| `test_toolkit_tools_generated` | `get_tools()` yields exactly the 4 tools with docstring-derived descriptions; excluded alias not exposed |
| `test_multi_origin_e2e_sqlite_wiki` | Real `SQLiteWikiStore` (tmp file) + fake vector store: grouped + merged payload correctness |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_vector_store():
    """Duck-typed store: async similarity_search(query, limit) -> list[SearchResult]."""
    ...

@pytest.fixture
async def sqlite_wiki_store(tmp_path):
    """Real SQLiteWikiStore seeded with a few pages (FTS-capable)."""
    ...

@pytest.fixture
def slow_origin():
    """SearchOrigin whose search() sleeps past the configured timeout."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `MultiStoreSearchToolkit(AbstractToolkit)` exists in `parrot_tools` and `get_tools()` exposes exactly: `store_search`, `batch_search`, `fts_search`, `list_search_origins`.
- [ ] The old `MultiStoreSearchTool` and its registry entry are **removed** (clean break); no references remain in `packages/` outside release notes/docs.
- [ ] All four origin families work through `SearchOrigin` adapters: vector stores (duck-typed), PageIndex, GraphIndex, ParrotWiki — each individually enable/disable-able by constructing the origin list.
- [ ] `store_search` responses contain BOTH grouped-by-origin sections (native ranking, origin description) AND a merged BM25-reranked, deduped top-k block.
- [ ] `batch_search` executes N queries × M origins through `asyncio.gather` (no `asyncio.to_thread` anywhere in the new code).
- [ ] `fts_search` runs only on FTS-capable origins (wiki / Arango / GraphIndex-SQLite) and reports skipped origins with a reason; no Postgres FTS code added.
- [ ] `PageIndexOrigin` supports `mode` in {`vector`, `hybrid`, `llm`} with default `hybrid`; the sync vector-walk path never blocks the event loop.
- [ ] Per-origin timeout defaults to 30 s, overridable per adapter; a timed-out or failing origin degrades to a status note and never fails the call.
- [ ] Core defines the `MultiSearch` protocol; `StoreRouter` FAN_OUT and `AbstractBot` type against it; `grep -r "parrot_tools" packages/ai-parrot/src/parrot/` shows no remaining core→toolkit import (even TYPE_CHECKING).
- [ ] `SearchOriginKind` lives in `parrot/models/stores.py`; `StoreType` members unchanged.
- [ ] All unit tests pass (`pytest packages/ai-parrot-tools/tests/ packages/ai-parrot/tests/ -v` scoped to changed areas).
- [ ] Updated `test_store_router_integration.py` passes against the new protocol.
- [ ] Documentation updated in `docs/` (configuration + migration/removal note).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> All references below re-verified on 2026-07-27 after rebase onto origin/dev
> (post FEAT-377 merge).

### Verified Imports
```python
from parrot.tools.abstract import AbstractTool           # used by current tool (parrot_tools/multistoresearch.py:28)
from parrot.tools.toolkit import AbstractToolkit         # packages/ai-parrot/src/parrot/tools/toolkit.py:207
from parrot.models import StoreType                      # parrot_tools/multistoresearch.py:29
from parrot.models.stores import SearchResult            # parrot_tools/multistoresearch.py:30
from parrot_tools.multistoresearch import MultiStoreSearchTool  # current registry target (parrot_tools/__init__.py:119) — REMOVED by this feature
```

### Existing Class Signatures
```python
# packages/ai-parrot-tools/src/parrot_tools/multistoresearch.py  (to be REPLACED)
class MultiStoreSearchTool(AbstractTool):                 # line 44
    args_schema = MultiStoreSearchSchema                  # line 51 (query: str, k: Optional[int])
    name = "multi_store_search"                           # line 92
    def __init__(self, pgvector_store=None, faiss_store=None, arango_store=None,
                 k: int = 10, k_per_store: int = 20,
                 bm25_weights: Optional[Dict[str, float]] = None,
                 enable_stores: Optional[List[StoreType]] = None, **kwargs)  # line 53
    def _rerank_with_bm25(self, query, results) -> List[SearchResult]        # line 201 — LIFT into toolkit
    async def _execute(self, query, k=None, **kwargs) -> List[Dict[str, Any]]  # line 291
    def _deduplicate_results(self, results, similarity_threshold=0.95)       # line 351 — LIFT into toolkit

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                               # line 207
    # auto-converts public async methods into tools (name=method, description=docstring)
    exclude_tools: tuple[str, ...] = ()                   # hide public async methods from tool generation
    tool_prefix: Optional[str] = None                     # optional namespace for generated tools

# packages/ai-parrot/src/parrot/models/stores.py
class StoreType(Enum):                                    # line 23 — PGVECTOR/FAISS/ARANGO only; DO NOT EXTEND
class SearchResult(BaseModel):                            # line 31
    id: str; content: str; metadata: Dict[str, Any]; score: float  # lower = closer for distance metrics

# packages/ai-parrot/src/parrot/knowledge/pageindex/retriever.py
class PageIndexRetriever:                                 # line 11
    async def search(self, query: str) -> TreeSearchResult  # line 38 — LLM tree search (spends tokens)

# packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py
class HybridPageIndexSearch:                              # line 52
    async def search(self, query: str, top_k: int = 10, use_bm25: bool = True,
                     use_llm_walk: bool = True, use_vec: bool = False,
                     use_embedding_walk: Optional[bool] = None,
                     rerank: bool = False) -> list[dict[str, Any]]  # line 288
    # result dicts carry node_id, title, summary, ...

# packages/ai-parrot/src/parrot/knowledge/pageindex/vector_walk.py
class FlatMatrixSearch:                                   # line 36
    def search(self, ...)                                 # line 60 — SYNC; must be kept off the event loop

# packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py
class GraphExpandedRetriever:                             # line 168
    async def search(self, query: str, seed_top_k: int = 10,
                     expansion: Optional[ExpansionConfig] = None,
                     budget: Optional[BudgetConfig] = None) -> GraphRetrievalResult  # line 658

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):                                 # line 268
    async def search_fts(self, query: str, category: Optional[str] = None,
                         limit: int = 10) -> list[dict[str, Any]]   # line 323
    async def search_vector(self, embedding: list[float],
                            limit: int = 10) -> list[dict[str, Any]]  # line 328
# SQLiteWikiStore implements both (store.py:803, 841); InMemoryWikiStore: file_store.py:522

# packages/ai-parrot-embeddings/src/parrot/stores/arango.py
class ArangoDBStore:
    async def fulltext_search(self, ...)                  # line 754 — FTS-capable vector store

# packages/ai-parrot/src/parrot/knowledge/wiki/search.py — exists; NOT used by this feature (decision)
class WikiCombinedSearch:                                 # line 32
    async def search(self, query, mode="combined", top_k=10, tree_name=None, weights=None)  # line 85
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `MultiStoreSearchToolkit` | `AbstractToolkit` | inheritance / auto tool generation | `parrot/tools/toolkit.py:207` |
| `MultiSearch` protocol | `StoreRouter._execute_fallback` | replaces `multistore_tool._execute(query, **kwargs)` call | `parrot/registry/routing/store_router.py:299-311` |
| `MultiSearch` protocol | `AbstractBot.configure_store_router` | retypes `multi_store_tool` param + `self._multi_store_tool` | `parrot/bots/abstract.py:577, 2040-2066, 3200` |
| registry entry | `parrot_tools/__init__.py` lazy map | `"multi_store_search": "parrot_tools.multistoresearch.MultiStoreSearchTool"` replaced | `parrot_tools/__init__.py:119` |
| `VectorStoreOrigin` | duck-typed stores | `await store.similarity_search(query, limit=k)` | current pattern at `parrot_tools/multistoresearch.py:105, 134, 163` |
| `ParrotWikiOrigin` | `BaseWikiStore` | `search_fts` / `search_vector` | `parrot/knowledge/wiki/store.py:323, 328` |
| guarded core import to remove | `parrot/bots/abstract.py` | `from parrot_tools.multistoresearch import MultiStoreSearchTool` try/except | `parrot/bots/abstract.py:117-129` |

### Does NOT Exist (Anti-Hallucination)
- ~~`PgVectorStore.fts_search`~~ / any full-text method on the Postgres store — does not exist; out of scope by decision.
- ~~FAISS FTS~~ — impossible; FAISS is vectors only.
- ~~`StoreType.PAGEINDEX` / `StoreType.GRAPHINDEX` / `StoreType.WIKI`~~ — `StoreType` has only PGVECTOR/FAISS/ARANGO and MUST stay that way; the new enum is `SearchOriginKind`.
- ~~`SearchOriginKind`, `OriginHit`, `OriginSection`, `MultiSearchResponse`, `SearchOrigin`, `MultiStoreSearchToolkit`, `MultiSearch` protocol~~ — none exist yet; **created by this feature**.
- ~~`parrot/interfaces/search.py`~~ — does not exist yet (module home for the protocol; `parrot/interfaces/tools.py` exists as a sibling reference).
- ~~`asyncio.to_thread` in current search paths~~ — everything relevant is async except `FlatMatrixSearch.search`.
- ~~GraphIndex public `fts_search`~~ — GraphIndex FTS is an internal SQLite detail (`persist_sqlite.py:242 _insert_nodes_fts`); exposing it through the adapter requires a reader-level query (see `sqlite_reader.py:320 search_symbols`), to be confirmed at implementation.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first throughout; `asyncio.gather(..., return_exceptions=True)` +
  per-origin `asyncio.wait_for` for isolation (extends the existing pattern at
  `parrot_tools/multistoresearch.py:319`).
- `AbstractToolkit` auto tool generation: every public async method is a tool;
  keep helpers private (`_`-prefixed) or in `exclude_tools`. Docstrings are the
  LLM tool descriptions — write them for the LLM (Google style).
- Pydantic models for all payloads (`OriginHit`, `OriginSection`,
  `MultiSearchResponse`).
- `self.logger` logging; no prints.
- Duck-typing for vector stores (no concrete store imports at load time) —
  preserve the current module's convention.
- Two-package discipline: core (`ai-parrot`) owns models + protocol; toolkit +
  adapters live in `ai-parrot-tools`. Import direction is tools→core only.

### Known Risks / Gotchas
- **Score heterogeneity**: vector distances (lower=better), wiki FTS ranks,
  graph scores are not comparable — merged block must rely on BM25-over-content
  (+ optional origin weights); the response `notes` must say so.
- **`FlatMatrixSearch.search` is sync** — wrap (executor) or precompute; never
  await-block the loop. This is the ONE place a thread offload is acceptable
  internally despite the no-`to_thread` decision for `batch_search` semantics
  (decide executor vs. refactor at implementation; document it).
- **LLM tree-walk mode** spends tokens and can exceed 30 s — the per-origin
  timeout + `llm` mode docstring warning mitigate; default mode is `hybrid`.
- **Grouped sections intentionally keep cross-origin duplicates** (the LLM
  should see each origin's genuine view); dedup applies only to the merged block.
- **Clean break blast radius**: StoreRouter FAN_OUT path, `AbstractBot`
  guarded import (lines 117-129) and `configure_store_router`, registry entry,
  integration tests — all enumerated in §2; nothing else imports the old tool
  (verified via grep 2026-07-27).
- **Wiki vector leg needs an embedder** — `WikiStore.search_vector` takes an
  embedding, not text; the adapter's vector leg is only active when an async
  `embedder` callable is configured, otherwise FTS-only.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `rank_bm25` | existing dep | merged top-k reranking (real path in current tool) |
| `bm25s` | existing optional | current code force-falls back to rank_bm25; keep optional or drop the dead path |
| `pydantic` | existing core dep | payload models |

No new external dependencies.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Flow type / base branch — *Resolved in brainstorm*: feature → dev.
- [x] Backwards compatibility strategy — *Resolved in brainstorm*: clean break; no deprecation shim; update all call sites in-feature.
- [x] `batch_search` concurrency model — *Resolved in brainstorm*: N queries fanned out via `asyncio.gather`; no `asyncio.to_thread`.
- [x] Result presentation — *Resolved in brainstorm*: both grouped-by-origin sections (native ranking + origin explanation) and merged BM25-reranked top-k.
- [x] Origin configuration style — *Resolved in brainstorm*: adapter registry (`SearchOrigin` contract + built-in adapters).
- [x] PageIndex retrieval mode — *Resolved in brainstorm*: configurable `vector | hybrid | llm`, default `hybrid`.
- [x] FTS on non-capable origins — *Resolved in brainstorm*: skip + note in output; no Postgres tsvector work in this feature.
- [x] Agent-facing tool names — *Resolved in brainstorm*: `store_search`, `batch_search`, `fts_search`, plus `list_search_origins`; `multi_store_search` retires.
- [x] Origin-kind enum location — *Resolved (spec Q&A 2026-07-27)*: new `SearchOriginKind` in `parrot/models/stores.py` (core), `StoreType` untouched.
- [x] StoreRouter FAN_OUT coupling — *Resolved (spec Q&A 2026-07-27)*: narrow `MultiSearch` protocol defined in core; core never imports `parrot_tools`, even under TYPE_CHECKING.
- [x] ParrotWiki adapter backend — *Resolved (spec Q&A 2026-07-27)*: call `WikiStore.search_fts`/`search_vector` directly; no `WikiCombinedSearch` delegation.
- [x] Per-origin timeout — *Resolved (spec Q&A 2026-07-27)*: 30 s default at toolkit level, per-origin override; timeout degrades to a section note.
- [ ] `list_search_origins` output: static config only, or include live health/staleness info (e.g. wiki plane staleness)? Default to static config in v1 unless trivially cheap. — *Owner: Jesus (decide during implementation)*
- [ ] Exact core home for the `MultiSearch` protocol (`parrot/interfaces/search.py` proposed; confirm against `parrot/interfaces/` layout at implementation). — *Owner: implementer*
- [ ] GraphIndex FTS leg for `fts_search`: expose via `sqlite_reader` query or mark GraphIndex `supports_fts=False` in v1? — *Owner: implementer*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in one worktree
  (`.claude/worktrees/feat-379-multistoresearchtool-parrotwiki`, branched from `dev`).
- **Rationale**: contract-first dependency chain (core models → protocol/decoupling
  → adapter contract → adapters → toolkit → clean-break migration → tests/docs);
  the clean break spans two packages (`ai-parrot`, `ai-parrot-tools`) and is
  safest reviewed and merged atomically. Adapter tasks (Modules 4–6) are
  mutually independent and could parallelize in principle, but they share the
  new package tree — coordination cost exceeds the benefit.
- **Cross-feature dependencies**: none pending. Touches hot files
  `parrot/bots/abstract.py` and `parrot/registry/routing/store_router.py` —
  re-check in-flight specs before starting implementation (FEAT-377/378 do not
  overlap as of 2026-07-27).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-27 | Jesus | Initial draft from brainstorm + spec Q&A |
