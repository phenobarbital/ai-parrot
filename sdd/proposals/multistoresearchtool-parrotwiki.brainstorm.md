---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: MultiStoreSearch Toolkit with PageIndex, GraphIndex & ParrotWiki Origins

**Date**: 2026-07-27
**Author**: Jesus
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

`MultiStoreSearchTool` (`packages/ai-parrot-tools/src/parrot_tools/multistoresearch.py`)
today searches only **vector-based** origins (pgVector, FAISS, ArangoDB) via
`similarity_search`, merges with BM25 reranking, and returns a flat top-k list.
Meanwhile the codebase has grown three non-vector retrieval planes that agents
cannot reach through multi-search:

- **PageIndex** (`parrot/knowledge/pageindex/`) — vectorless, tree-based
  reasoning RAG (LLM tree-walk, vector-walk, and hybrid modes).
- **GraphIndex** (`parrot/knowledge/graphindex/`) — 4-phase graph retrieval
  (seed → expand → community annotation → assembly).
- **ParrotWiki / LLM-Wiki** (`parrot/knowledge/wiki/`) — `WikiStore` SQLite
  retrieval plane with native FTS + vector search.

Agents configured for multi-search context retrieval get only the vector view
of knowledge; tree, graph, and wiki knowledge is invisible. Additionally the
component is a single `AbstractTool` — there is no room for sibling operations
(batch search, full-text search, origin introspection) without schema bloat.

**Who is affected**: agent developers wiring RAG context; end users of agents
whose answers miss knowledge that lives only in PageIndex/GraphIndex/wiki;
the FEAT-111 `StoreRouter`, whose FAN_OUT policy delegates to this tool.

**Decision (user, 2026-07-27)**: convert the tool into a toolkit
(`AbstractToolkit`) as a **clean break** — no deprecation shim — exposing
`store_search`, `batch_search`, `fts_search`, and `list_search_origins`.

## Constraints & Requirements

- **Async-first**: all origin searches run concurrently via `asyncio.gather`
  (user decision — no `asyncio.to_thread`; every origin entry point is async
  except PageIndex `FlatMatrixSearch.search`, which is sync and must be
  wrapped/kept off the hot path).
- **Clean break**: `MultiStoreSearchTool` is removed/replaced; all call sites
  updated in the same feature (StoreRouter FAN_OUT, `AbstractBot`, registry
  entry, integration tests).
- **Origin-attributed output**: results must carry the origin name AND a
  human/LLM-readable explanation of what that origin is, so the LLM can weigh
  the evidence itself.
- **Output shape (user decision)**: BOTH grouped-by-origin sections (native
  ranking preserved) AND a merged BM25-reranked top-k block.
- **FTS scope (user decision)**: `fts_search` runs only on FTS-capable
  origins (wiki, Arango, GraphIndex-SQLite); non-capable origins are skipped
  with a note in the output. No new Postgres tsvector work in this feature.
- **PageIndex retrieval mode (user decision)**: configurable per origin
  (`vector | hybrid | llm`), default `hybrid`.
- Per-origin failures must degrade gracefully (log + note), never fail the
  whole search — same philosophy as today's `return_exceptions=True`.
- No LangChain; Pydantic models for all structured data; Google-style
  docstrings (they become the LLM tool descriptions via `AbstractToolkit`).

---

## Options Explored

### Option A: Origin-Adapter Toolkit (`SearchOrigin` protocol + `MultiStoreSearchToolkit`)

A new `MultiStoreSearchToolkit(AbstractToolkit)` that owns a **registry of
origin adapters**. A `SearchOrigin` contract (Pydantic-configured adapter
classes, or a `Protocol`) defines: `name`, `kind` (enum), `description`
(the origin explanation surfaced to the LLM), `async search(query, k)`,
`supports_fts: bool`, and optional `async fts_search(query, k)`. Built-in
adapters wrap the seven known origins: pgvector / FAISS / Arango (duck-typed
`similarity_search`, as today), PageIndex (mode-configurable), GraphIndex
(`GraphExpandedRetriever.search`), and ParrotWiki (`WikiStore.search_fts` +
`search_vector`, or `WikiCombinedSearch`). The toolkit's public async methods
become the agent tools automatically: `store_search`, `batch_search`,
`fts_search`, `list_search_origins`. BM25 rerank + dedup logic is lifted from
the current tool into a shared helper used by the merged top-k block.

✅ **Pros:**
- Uniform extension point — adding origin #8 is one adapter class, zero
  toolkit changes; matches the user's "configure which kind of store" goal.
- Normalizes heterogeneous result types (`SearchResult`, `TreeSearchResult`,
  `GraphRetrievalResult`, wiki dict rows) at the adapter boundary — the
  toolkit core stays type-clean.
- `supports_fts` flag makes the skip-and-note FTS behavior declarative.
- Adapters are unit-testable in isolation with fake backends.

❌ **Cons:**
- Most new surface area (adapter contract + 5–7 adapter classes + result
  normalization model).
- StoreRouter FAN_OUT and `AbstractBot.configure_store_router` must be
  migrated to the new API in the same feature (clean break cost).

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `rank_bm25` | merged top-k reranking | already used by current tool (fallback path is the real path) |
| `bm25s` | optional faster BM25 | already optional-imported; current code force-falls back — keep as-is or drop |
| `pydantic` | adapter config + normalized result model | already a core dep |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch.py` — BM25 rerank (`_rerank_with_bm25`), dedup (`_deduplicate_results`), per-store error isolation pattern.
- `packages/ai-parrot/src/parrot/tools/toolkit.py:207` — `AbstractToolkit` (auto tool generation from public async methods, `exclude_tools`, `tool_prefix`).
- `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py:52` — `HybridPageIndexSearch.search`.
- `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py:168` — `GraphExpandedRetriever.search`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:268` — `BaseWikiStore.search_fts` / `search_vector`.

---

### Option B: Extend the Existing Tool In-Place (named params, stay `AbstractTool`)

Keep `MultiStoreSearchTool(AbstractTool)` and add `pageindex=`, `graphindex=`,
`wiki=` constructor params plus `_search_pageindex/_search_graphindex/_search_wiki`
methods mirroring the existing `_search_pgvector` style. Extend the input
schema with a `mode` field (`vector | fts | batch`) to emulate the extra
operations inside one tool.

✅ **Pros:**
- Smallest diff; no call-site migration (StoreRouter/AbstractBot untouched).
- Follows the exact code style already in the file.

❌ **Cons:**
- Contradicts two explicit user decisions (toolkit conversion, clean break).
- One tool schema multiplexing three operations is worse for the LLM than
  three well-named tools; `batch_search` (list-of-queries) fits badly.
- Constructor grows linearly with every future origin; no `list_search_origins`
  introspection surface.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `rank_bm25` | reranking | unchanged |

🔗 **Existing Code to Reuse:**
- Everything in `multistoresearch.py` stays; only additive edits.

---

### Option C: Thin Toolkit Façade over `WikiCombinedSearch` + `StoreRouter` (reuse-maximal, unconventional)

Do not build new origin plumbing. `parrot/knowledge/wiki/search.py:32` already
implements `WikiCombinedSearch` — unified search across PageIndex + GraphIndex
+ WikiStore with weighted merging (`mode="combined" | "pageindex" | "graphindex"`).
The new toolkit would compose exactly two legs per query: (1) the existing
vector-store fan-out (lifted from the current tool) and (2) a
`WikiCombinedSearch.search()` call covering PageIndex/GraphIndex/wiki, then
merge the two legs with origin attribution.

✅ **Pros:**
- Massive reuse — PageIndex/GraphIndex/wiki merging, weighting, and result
  normalization (`WikiSearchResult`) already exist and are tested
  (`tests/knowledge/wiki/`).
- Fastest route to all six origins working end-to-end.

❌ **Cons:**
- `WikiCombinedSearch` assumes the three knowledge planes belong to ONE wiki
  deployment; an agent wanting GraphIndex-only or PageIndex-against-a-PDF-tree
  without a wiki store fights the abstraction.
- Per-origin enable/disable (the user's core requirement) is awkward — it's a
  `mode` string, not a registry.
- FTS lives inside `WikiStore` only; Arango `fulltext_search` doesn't fit the
  façade, so `fts_search` still needs origin-level plumbing anyway.
- Two different merging schemes stacked (wiki weights, then BM25) is hard to
  explain and tune.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `rank_bm25` | outer-leg reranking | unchanged |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/search.py:32` — `WikiCombinedSearch` (init takes toolkits or a `WikiStore` + embedder; `search()` at :85).
- `packages/ai-parrot/src/parrot/registry/routing/store_router.py` — FAN_OUT fallback fan-out loop as reference.

---

## Recommendation

**Option A** is recommended because:

- It is the only option that satisfies all four user decisions simultaneously
  (toolkit conversion, clean break, per-origin enable/disable, grouped+merged
  output with origin explanations).
- The adapter boundary is where the real complexity of this feature lives:
  the four origin families return four different result shapes
  (`SearchResult`, `TreeSearchResult`, `GraphRetrievalResult`, wiki dicts).
  Option A confronts that once, explicitly; B and C smear it across the tool
  body or stack two merge algorithms.
- The trade-off is accepted scope: ~5–7 adapter classes and migration of the
  three call sites (`StoreRouter` FAN_OUT, `AbstractBot`, `parrot_tools`
  registry). This is bounded and enumerated in Impact & Integration.
- Option C is not wasted: the **ParrotWiki adapter** may internally delegate
  to `WikiCombinedSearch`/`WikiStore`, capturing its reuse benefit inside one
  adapter without inheriting its coupling.

---

## Feature Description

### User-Facing Behavior

An agent developer configures the toolkit with any subset of origins:

- vector stores (pgvector / FAISS / Arango instances, duck-typed
  `similarity_search` as today),
- a PageIndex source (tree/toolkit + retrieval `mode`: `vector | hybrid | llm`,
  default `hybrid`),
- a GraphIndex source (`GraphExpandedRetriever` or factory-produced toolkit),
- a ParrotWiki source (`WikiStore`, optionally with embedder for the vector leg).

The agent then sees four tools (docstrings become tool descriptions):

- **`store_search(query, k)`** — fan out the query to all enabled origins
  concurrently; return grouped-by-origin sections (each with the origin's
  name, an explanation of what that origin is and how its ranking works, and
  its native-ranked results) followed by a merged BM25-reranked top-k block.
- **`batch_search(queries, k)`** — N queries × M origins via a single
  `asyncio.gather`; results grouped per query, each following the
  `store_search` shape.
- **`fts_search(query, k)`** — full-text search on FTS-capable origins only
  (ParrotWiki `search_fts`, Arango `fulltext_search`, GraphIndex SQLite FTS);
  output explicitly notes which enabled origins were skipped and why.
- **`list_search_origins()`** — enumerate enabled origins with kind,
  description, FTS capability, and configuration summary (e.g. PageIndex
  mode) so the LLM can plan its retrieval strategy.

### Internal Behavior

1. **Adapter contract** — each origin is wrapped in a `SearchOrigin` adapter
   exposing `name`, `kind` (new enum — see Open Questions; `StoreType` stays
   DB-only), `description`, `supports_fts`, `async search(query, k)`, and
   optional `async fts_search(query, k)`. Adapters normalize their backend's
   native result type into one Pydantic result model
   (content, score, metadata, origin, native_rank, id).
2. **Toolkit core** — holds the ordered adapter list; `store_search` gathers
   `adapter.search()` coroutines with `return_exceptions=True`; failures
   become per-origin notes, never exceptions. Dedup (ID, then content hash)
   and BM25 rerank are applied only for the merged block; grouped sections
   keep native order.
3. **PageIndex adapter** — dispatches by mode: `vector` →
   `FlatMatrixSearch.search` (sync — wrap so it never blocks the loop),
   `hybrid` → `HybridPageIndexSearch.search`, `llm` →
   `PageIndexRetriever.search` (documented as token-spending).
4. **Origin explanations** — each adapter carries a default description
   ("results come from a hierarchical document tree…", "…from a typed
   knowledge graph with community context", etc.), overridable at
   configuration time; these strings are embedded in the grouped output.
5. **Clean-break migration** — `StoreRouter._execute_fallback` FAN_OUT stops
   calling `multistore_tool._execute` and instead accepts the toolkit (or its
   `store_search` coroutine); `AbstractBot.configure_store_router`'s
   `multi_store_tool` parameter is retyped; `parrot_tools/__init__.py`
   registry maps to the new toolkit; old module deleted.

### Edge Cases & Error Handling

- **No origins enabled** → tools return a structured "no origins configured"
  message (not an exception), mirroring today's warning.
- **One origin raises / times out** → its section reports the failure; other
  sections and the merged block proceed. Consider a per-origin timeout so one
  slow backend (LLM tree-walk!) can't stall `store_search`.
- **`fts_search` with zero FTS-capable origins enabled** → returns the
  skip-notes only, stating no capable origin is configured.
- **`batch_search` with an empty query list** → empty result, no gather.
- **Duplicate content across origins** (e.g. same doc in pgvector and wiki)
  → dedup only in the merged block; grouped sections intentionally keep
  duplicates so the LLM sees each origin's genuine view.
- **Score heterogeneity** — vector distances (lower=better in `SearchResult`),
  wiki FTS ranks, graph relevance scores are NOT comparable; merged block
  relies on BM25-over-content (+ origin weight) exactly because of this;
  document it in tool output.

---

## Capabilities

### New Capabilities
- `multistore-search-toolkit`: `MultiStoreSearchToolkit(AbstractToolkit)` with `store_search`, `batch_search`, `fts_search`, `list_search_origins`.
- `search-origin-adapters`: `SearchOrigin` contract + built-in adapters (vector stores, PageIndex, GraphIndex, ParrotWiki) with normalized result model and origin descriptions.

### Modified Capabilities
- `router-based-adaptive-rag` (FEAT-111): `StoreRouter` FAN_OUT delegation retargeted from `MultiStoreSearchTool._execute` to the new toolkit.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch.py` | replaces | clean break: tool → toolkit + adapters (new module or package `parrot_tools/multistoresearch/`) |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py:119` | modifies | registry entry `"multi_store_search"` → new toolkit path/name |
| `packages/ai-parrot/src/parrot/registry/routing/store_router.py:189,303,311` | modifies | FAN_OUT fallback calls the toolkit instead of `._execute()` |
| `packages/ai-parrot/src/parrot/bots/abstract.py:117,577,2040-2066,3200` | modifies | `_multi_store_tool` wiring + `configure_store_router(multi_store_tool=...)` retyped |
| `packages/ai-parrot/tests/integration/rag/test_store_router_integration.py` | modifies | fakes built against the new API |
| `parrot/knowledge/{pageindex,graphindex,wiki}` | depends on | consumed read-only via adapters; no changes expected |
| `parrot/models/stores.py` | extends (maybe) | new origin-kind enum lives here or in `parrot/models`; `StoreType` untouched |

No new external dependencies. Breaking change is intentional and internal
(the toolkit ships from `ai-parrot-tools`; release notes must flag the
removal of `MultiStoreSearchTool`).

---

## Code Context

### User-Provided Code

(none — user provided requirements prose only)

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot-tools/src/parrot_tools/multistoresearch.py:44
class MultiStoreSearchTool(AbstractTool):
    args_schema = MultiStoreSearchSchema  # line 51 (query: str, k: Optional[int])
    def __init__(self, pgvector_store=None, faiss_store=None, arango_store=None,
                 k: int = 10, k_per_store: int = 20,
                 bm25_weights: Optional[Dict[str, float]] = None,
                 enable_stores: Optional[List[StoreType]] = None, **kwargs): ...  # line 53
    async def _execute(self, query: str, k: Optional[int] = None, **kwargs) -> List[Dict[str, Any]]: ...  # line 291
    def _rerank_with_bm25(self, query, results) -> List[SearchResult]: ...  # line 201
    def _deduplicate_results(self, results, similarity_threshold=0.95) -> List[SearchResult]: ...  # line 351

# From packages/ai-parrot/src/parrot/tools/toolkit.py:207
class AbstractToolkit(ABC):
    # auto-converts public async methods into tools (name=method, description=docstring)
    exclude_tools: tuple[str, ...] = ()   # hide public async methods from tool generation
    tool_prefix: Optional[str] = None     # optional namespace for every generated tool

# From packages/ai-parrot/src/parrot/models/stores.py:23
class StoreType(Enum):
    PGVECTOR = "pgvector"; FAISS = "faiss"; ARANGO = "arango"  # DB stores ONLY

# From packages/ai-parrot/src/parrot/models/stores.py:31
class SearchResult(BaseModel):
    id: str; content: str; metadata: Dict[str, Any]; score: float  # lower = closer for distance metrics

# From packages/ai-parrot/src/parrot/knowledge/pageindex/retriever.py:11,38
class PageIndexRetriever:
    async def search(self, query: str) -> TreeSearchResult: ...  # LLM tree search (spends tokens)

# From packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py:52,288
class HybridPageIndexSearch:
    async def search(self, query: str, top_k: int = 10, use_bm25: bool = True,
                     use_llm_walk: bool = True, use_vec: bool = False,
                     use_embedding_walk: Optional[bool] = None,
                     rerank: bool = False) -> list[dict[str, Any]]: ...
    # each result dict has node_id, title, summary, ...

# From packages/ai-parrot/src/parrot/knowledge/pageindex/vector_walk.py:36,60
class FlatMatrixSearch:
    def search(self, ...): ...  # SYNC — must not be awaited / must not block the loop

# From packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py:168,658
class GraphExpandedRetriever:
    async def search(self, query: str, seed_top_k: int = 10,
                     expansion: Optional[ExpansionConfig] = None,
                     budget: Optional[BudgetConfig] = None) -> GraphRetrievalResult: ...

# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py:268,323,328
class BaseWikiStore(ABC):
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]: ...
    async def search_vector(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]: ...
# SQLiteWikiStore implements both (store.py:803, 841); InMemoryWikiStore in file_store.py:522

# From packages/ai-parrot/src/parrot/knowledge/wiki/search.py:32,47,85
class WikiCombinedSearch:
    def __init__(self, pageindex_toolkit, graphindex_toolkit,
                 default_weights=None, store: Optional[WikiStore] = None,
                 embedder: Optional[Callable[[str], Awaitable[list[float]]]] = None): ...
    async def search(self, query: str, mode: str = "combined", top_k: int = 10,
                     tree_name: Optional[str] = None, weights=None) -> list[WikiSearchResult]: ...

# From packages/ai-parrot-embeddings/src/parrot/stores/arango.py:754
class ArangoDBStore:
    async def fulltext_search(self, ...): ...  # FTS-capable vector store

# From packages/ai-parrot/src/parrot/registry/routing/store_router.py:299-311
# StoreRouter._execute_fallback: FAN_OUT policy calls `multistore_tool._execute(query, **search_kwargs)`
# From packages/ai-parrot/src/parrot/bots/abstract.py:577,2040,3200
# AbstractBot holds `self._multi_store_tool` and passes it to StoreRouter as `multistore_tool=`
```

#### Verified Imports
```python
from parrot.tools.abstract import AbstractTool          # used by current tool (multistoresearch.py:28)
from parrot.tools.toolkit import AbstractToolkit        # packages/ai-parrot/src/parrot/tools/toolkit.py:207
from parrot.models import StoreType                     # multistoresearch.py:29
from parrot.models.stores import SearchResult           # multistoresearch.py:30
from parrot_tools.multistoresearch import MultiStoreSearchTool  # current registry path (parrot_tools/__init__.py:119)
```

#### Key Attributes & Constants
- `MultiStoreSearchTool.name = "multi_store_search"` (multistoresearch.py:92)
- registry lazy-map entry `"multi_store_search": "parrot_tools.multistoresearch.MultiStoreSearchTool"` (parrot_tools/__init__.py:119)
- `StoreRouter._execute_fallback(..., multistore_tool, ...)` (store_router.py:299-311)
- GraphIndex SQLite FTS internals: `_insert_nodes_fts` (graphindex/persist_sqlite.py:242)

### Does NOT Exist (Anti-Hallucination)
- ~~`PgVectorStore.fts_search` / any full-text method on PgVectorStore~~ — Postgres store has NO FTS method today (out of scope by user decision).
- ~~FAISS FTS~~ — impossible; FAISS is vectors only.
- ~~`StoreType.PAGEINDEX` / `StoreType.GRAPHINDEX` / `StoreType.WIKI`~~ — `StoreType` has only PGVECTOR/FAISS/ARANGO and is documented as the DB-store source of truth; do not extend it casually.
- ~~`MultiStoreSearchToolkit`~~ — does not exist yet; this feature creates it.
- ~~`asyncio.to_thread` usage in current search paths~~ — everything relevant is already async except `FlatMatrixSearch.search`.

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. Adapter classes (PageIndex, GraphIndex, ParrotWiki, vector) are mutually independent once the `SearchOrigin` contract + result model land, but the toolkit core, the clean-break migration (StoreRouter/AbstractBot/registry), and the adapters all touch the same new module tree — sequencing in one worktree is simpler than coordinating several.
- **Cross-feature independence**: touches `parrot/bots/abstract.py` and `parrot/registry/routing/store_router.py` — both are hot files; check in-flight specs (FEAT-378 devloop-enhancement does not overlap). No shared files with knowledge/* features expected (read-only consumption).
- **Recommended isolation**: per-spec (single worktree, sequential tasks).
- **Rationale**: contract-first dependency chain (contract → adapters → toolkit → migration → tests); a clean break across two packages (`ai-parrot-tools`, `ai-parrot`) is safest reviewed and merged atomically.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus*: feature → dev.
- [x] Backwards compatibility strategy — *Owner: Jesus*: clean break; no deprecation shim; update all call sites in-feature.
- [x] `batch_search` concurrency model — *Owner: Jesus*: N queries fanned out via `asyncio.gather`; no `asyncio.to_thread`.
- [x] Result presentation — *Owner: Jesus*: both grouped-by-origin sections (native ranking + origin explanation) and merged BM25-reranked top-k.
- [x] Origin configuration style — *Owner: Jesus*: adapter registry (`SearchOrigin` contract + built-in adapters).
- [x] PageIndex retrieval mode — *Owner: Jesus*: configurable `vector | hybrid | llm`, default `hybrid`.
- [x] FTS on non-capable origins — *Owner: Jesus*: skip + note in output; no Postgres tsvector work in this feature.
- [x] Agent-facing tool names — *Owner: Jesus*: `store_search`, `batch_search`, `fts_search`, plus `list_search_origins`; `multi_store_search` name retires.
- [ ] Where does the origin-kind enum live — extend `parrot/models/stores.py` with a new `SearchOriginKind` enum (keeping `StoreType` DB-only), or define it inside `parrot_tools`? Cross-package import direction matters (StoreRouter in core references the toolkit type only under TYPE_CHECKING today). — *Owner: Jesus*
- [ ] StoreRouter FAN_OUT contract: should the router depend on the toolkit instance, or on a narrower `search(query, k)` callable/protocol so core never imports `parrot_tools` types? — *Owner: Jesus*
- [ ] Per-origin timeout for `store_search`/`batch_search` (LLM tree-walk mode can be slow) — default value and whether it's per-origin-configurable. — *Owner: Jesus*
- [ ] Should the ParrotWiki adapter delegate to `WikiCombinedSearch` (reuses weighting/normalization) or call `WikiStore.search_fts`/`search_vector` directly (thinner, no PageIndex/GraphIndex coupling)? — *Owner: Jesus*
- [ ] `list_search_origins` output: include live health/staleness info (e.g. wiki plane staleness) or static config only? — *Owner: Jesus*
