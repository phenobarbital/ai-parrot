# Brainstorm: Router-Based Adaptive RAG (Store-Level)

**Date**: 2026-04-20
**Author**: Jesus
**Status**: exploration
**Recommended Option**: C
**Proposed Feature ID**: FEAT-111 (next available; FEAT-004 was reused by `graphic-panel-display`)

---

## Problem Statement

AI-Parrot has a functional **strategy-level** intent router (`IntentRouterMixin`, FEAT-069/070) that picks between `VECTOR_SEARCH`, `GRAPH_PAGEINDEX`, `DATASET`, `TOOL_CALL`, `FREE_LLM`, `MULTI_HOP`, `FALLBACK`, and `HITL`.

However, **within** `VECTOR_SEARCH`, there is no routing: `AbstractBot._build_vector_context()` dispatches to a single `self.store`. When multiple vector-like stores coexist (PgVector for dense, FAISS for in-memory, ArangoDB for graph), the only multi-store option today is `MultiStoreSearchTool`, which **always fans out in parallel** to every configured store and reranks with BM25. This is wasteful:

- Queries whose shape clearly suits one backend (e.g., keyword queries → BM25/PgVector FTS, graph traversal queries → ArangoDB) still hit all stores.
- Embedding calls, network round-trips, and BM25 rerank overhead pay for retrievals that were never going to matter.
- There is no way to express "prefer PgVector; escalate to parallel only when uncertain."

**Gap**: a per-query **store-level router** that returns a ranked, weighted set of `(store, confidence)` tuples, with fallback to parallel fan-out when ambiguous. It must plug into the existing `IntentRouterMixin` / `AbstractBot._build_vector_context()` path without duplicating infrastructure.

**Affected users**:
- Agent/bot developers building RAG-enabled bots (`AbstractBot` subclasses).
- Ops: lower latency and embedding cost under load.
- End users (indirectly): faster, more relevant answers.

---

## Constraints & Requirements

- **Hybrid routing**: deterministic heuristic rules first; LLM classifier fallback (≤ 800ms budget).
- **Output semantics**: ranked/weighted list of stores with confidence scores, not a single winner.
- **Uncertainty handling**: when top-1 − top-2 confidence margin < `Y`, fall back to parallel fan-out.
- **Coexistence**: `MultiStoreSearchTool` must continue to work; router is additive, not a replacement.
- **Primary consumer**: `AbstractBot.knowledge_base` / `_build_vector_context()` path (implicit activation).
- **Ontology-as-signal**: `parrot/knowledge/ontology/` must annotate the query (entities, relations) to feed the routing decision; ontology also remains queryable as a graph store.
- **Configurability**: rule set defaults hardcoded in a `StoreRouter` class + per-agent YAML overrides.
- **Caching**: in-memory LRU per bot instance, keyed by normalized query hash.
- **No confident match policy**: agent-configurable (`fan-out` | `empty` | `first-available` | `raise`).
- **Performance**: fast path overhead < 5ms; LLM path < 1s; cache hit < 1ms.
- **Backwards compatibility**: bots not configuring the router behave exactly as today.
- **Async-first**: no blocking I/O, all retrieval paths remain `async`.

---

## Options Explored

### Option A: Extend `MultiStoreSearchTool` with internal router

Enrich the existing `MultiStoreSearchTool` so that, before fanning out, it runs a `StoreRouter` that decides which subset of stores to actually query. When the router is confident, only the selected stores are invoked; when it's uncertain, the tool falls back to the current all-stores-parallel behavior.

✅ **Pros:**
- Smallest blast radius — all changes live in one file.
- Backward compatible by construction: default config preserves today's parallel behavior.
- Lowest risk of MRO / mixin interaction bugs.

❌ **Cons:**
- Only helps agents that use `MultiStoreSearchTool` as a Tool. Does **not** help the implicit `AbstractBot.knowledge_base` / `_build_vector_context` path — which was the explicit primary consumer (Q4 = a).
- Duplicates concepts that `IntentRouterMixin` already owns (keyword maps, LLM fallback, confidence thresholds).
- Ontology signal would have to be wired into the tool separately — doesn't compose with strategy-level routing.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `bm25s` | existing reranker | already imported |
| `rank-bm25` | fallback reranker | already imported |
| (no new deps) | — | — |

🔗 **Existing Code to Reuse:**
- `parrot/tools/multistoresearch.py` — the tool itself, extended with a pre-filter hook
- `parrot/stores/abstract.py:AbstractStore.similarity_search` — unified async store interface

---

### Option B: New `BaseRetriever` hierarchy under `parrot/rag/`

The original FEAT-004 plan: build a fresh `parrot/rag/` package with `BaseRetriever`, `DenseRetriever`, `SparseRetriever`, `GraphRetriever`, `RAGRouter`, and `RAGPipeline`. Each retriever wraps one store; `RAGRouter` selects between them; `RAGPipeline` orchestrates retrieval + rerank + context injection. Bots import `RAGPipeline` and plug it into `knowledge_base`.

✅ **Pros:**
- Clean academic abstraction; matches naming in the RAG literature.
- Independent of `IntentRouterMixin` — testable in isolation.
- Explicit typed interface (`BaseRetriever`) for every store.

❌ **Cons:**
- **Heavy duplication** with existing infrastructure: `IntentRouterMixin` already has keyword maps, LLM fallback via `self.invoke()`, `IntentRouterConfig`, `CapabilityRegistry`, HITL, cascades, traces. Building a parallel set of these in `parrot/rag/` means two routing engines to maintain.
- `AbstractStore.similarity_search()` is already a uniform async interface — wrapping each store in a `BaseRetriever` is largely ceremonial.
- The "route at strategy level + route at store level" split becomes confusing when both layers have their own configs, caches, and routing logic.
- Higher effort with the highest risk of drift between the two routing layers.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `rank-bm25` | BM25 sparse retrieval | already imported |
| `bm25s` | faster BM25 | already imported |
| `python-arango` | ArangoDB graph traversal | already imported |
| (no new deps) | — | — |

🔗 **Existing Code to Reuse:**
- `parrot/stores/postgres.py:PgVectorStore`
- `parrot/stores/arango.py:ArangoDBStore`
- `parrot/stores/faiss_store.py:FAISSStore`
- `parrot/tools/multistoresearch.py` — reranking logic worth extracting into a utility

---

### Option C: `StoreRouter` as sub-layer under `IntentRouterMixin` **(RECOMMENDED)**

Introduce a new `StoreRouter` class (proposed location: `parrot/registry/routing/store_router.py`) that is invoked **after** `IntentRouterMixin` selects `VECTOR_SEARCH`, but **before** `AbstractBot._build_vector_context()` dispatches to `self.store`. The router:

1. **Pre-annotates** the query using `OntologyIntentResolver` (entities, relations, pattern hints). Ontology annotations are cached alongside the routing decision.
2. **Fast path**: applies heuristic rules (defaults hardcoded; per-agent YAML overrides merged on top, mirroring `IntentRouterConfig.custom_keywords`) to compute preliminary store scores.
3. **LLM path (fallback)**: when the top-1 vs top-2 margin is below `Y`, calls `self.invoke()` with a small JSON-schema prompt listing stores + ontology annotations + query, and parses the returned ranking (same parsing pattern as `IntentRouterMixin._parse_invoke_response`).
4. **LRU cache**: in-memory `functools.lru_cache`-style cache per bot instance (wrapped over `OrderedDict` for async-safety), keyed by `(normalized_query_hash, store_fingerprint)`.
5. **No-confident-match policy**: per-agent enum `StoreFallbackPolicy` — `FAN_OUT` (delegates to `MultiStoreSearchTool`-style parallel), `EMPTY`, `FIRST_AVAILABLE`, `RAISE`.
6. **Returns** a `StoreRoutingDecision(rankings: list[(StoreType, confidence)], fallback_used: bool)` that `_build_vector_context` consumes.

`MultiStoreSearchTool` remains unchanged as a standalone Tool; agents can opt to use it explicitly (Q3 = coexist). Ontology is both a **pre-annotator** and remains queryable as `GRAPH_PAGEINDEX` strategy (Q7 = both).

✅ **Pros:**
- Reuses `IntentRouterMixin` infrastructure (LLM fallback pattern, `invoke()` contract, config schema shape, parsing logic) — no routing-engine duplication.
- Directly plugs into the primary consumer (`AbstractBot._build_vector_context`) so every RAG-enabled bot benefits implicitly (Q4 = a).
- Ontology annotations feed both the strategy router (existing) and the new store router, giving one unified signal.
- Coexists cleanly with `MultiStoreSearchTool` (fallback mode delegates to its parallel+rerank pipeline) — no replacement needed.
- Per-agent YAML override matches the existing `IntentRouterConfig.custom_keywords` pattern; developers already know it.
- Small, layered, testable — unit tests per decision point.

❌ **Cons:**
- Touches `AbstractBot._build_vector_context()` (`parrot/bots/abstract.py:2129`) — needs careful backward-compat flag so unconfigured bots keep current behavior.
- Requires extracting the LLM-route prompt/parse helpers from `IntentRouterMixin` into a shared utility to avoid a minor copy-paste (small refactor).
- Ontology pre-annotation adds ~0-5ms when fast-path keywords already matched; acceptable but worth measuring.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | config + decision models | v2 already project-wide |
| `bm25s` / `rank-bm25` | reused for fallback fan-out reranking | already imported |
| (no new deps) | — | — |

🔗 **Existing Code to Reuse:**
- `parrot/bots/mixins/intent_router.py` — LLM-route prompt + `_parse_invoke_response` pattern to be extracted into a shared helper
- `parrot/registry/capabilities/models.py` — `IntentRouterConfig` shape to mirror for `StoreRouterConfig`
- `parrot/knowledge/ontology/intent.py:OntologyIntentResolver` — query pre-annotation (soft-deprecated for *strategy* routing but still useful as a **signal source** for store routing)
- `parrot/tools/multistoresearch.py` — fan-out + BM25 rerank as the `FAN_OUT` fallback implementation
- `parrot/stores/abstract.py:AbstractStore.similarity_search` — store-agnostic invocation
- `parrot/bots/abstract.py:_build_vector_context` (line 2129) — integration point

---

## Recommendation

**Option C** is recommended.

The existing `IntentRouterMixin` already solves ~70% of the routing problem — at the strategy level. The user's actual gap is **one level deeper**: when strategy = `VECTOR_SEARCH`, which store(s)? Building Option B (full `parrot/rag/` hierarchy) would duplicate all the thresholds, LLM-fallback code, config plumbing, and trace machinery we already have. Option A doesn't reach the primary consumer (`AbstractBot._build_vector_context`) the user explicitly chose (Q4 = a).

Option C is the minimum-viable addition: a new layer that **composes** with the existing router. It reuses the LLM-fallback pattern, the YAML override pattern, and the ontology module, while delivering exactly the missing store-selection layer. Worst-case fallback reuses `MultiStoreSearchTool`'s existing fan-out+rerank, so no regression for the multi-store tool path.

What we trade off:
- **Purity**: there is no clean `BaseRetriever` ABC; instead store routing leans on `AbstractStore.similarity_search` which is already uniform. We accept this as simpler and less ceremonial.
- **Independence**: `StoreRouter` is tightly coupled to the bot path. We accept this because it's the primary consumer; callers wanting standalone multi-store routing can use `MultiStoreSearchTool`.

---

## Feature Description

### User-Facing Behavior

Agent developers opt in by calling a new `configure_store_router()` method alongside `configure_router()`:

```
agent = MyAgent(...)
agent.configure_router(intent_config, capability_registry)   # existing strategy router
agent.configure_store_router(store_config)                   # NEW store router
```

With `store_config` shaped like `IntentRouterConfig` — hardcoded defaults merged with per-agent YAML overrides (rules, weights, margin threshold `Y`, fallback policy, cache size).

End users notice:
- Faster first-token latency on queries that cleanly match one store (no unnecessary parallel calls).
- Identical answer quality on ambiguous queries (fan-out fallback engages).

### Internal Behavior

Flow when `IntentRouterMixin` resolves `VECTOR_SEARCH`:

1. `_run_vector_search()` is entered (existing).
2. `_build_vector_context()` now checks for an active `StoreRouter` on `self`.
3. If none → today's behavior (dispatch to `self.store`).
4. If active → router pipeline:
   a. **Cache lookup** via LRU keyed by `(normalized_query_hash, store_fingerprint)`. Hit → return cached decision.
   b. **Ontology pre-annotation** via `OntologyIntentResolver` (when ontology is configured) → produces entities/relation hints.
   c. **Fast path**: apply heuristic rules (defaults + YAML overrides) to compute per-store scores.
   d. **Margin check**: if `score[0] − score[1] ≥ Y` → done. Otherwise, **LLM path** via `self.invoke()` with a structured-output prompt; resulting ranking merges with fast-path scores (weighted average).
   e. **Decision assembly**: emit `StoreRoutingDecision(rankings, fallback_used)`; cache it.
   f. **Execution**: call top-N stores (N configurable, default 1). If `rankings` is empty or all below threshold → apply `StoreFallbackPolicy`.
5. Returned context feeds back into `_build_vector_context()` as today.

### Edge Cases & Error Handling

- **No stores configured**: `StoreRouter` no-ops, bot continues as today.
- **All stores below threshold + policy=EMPTY**: `_build_vector_context` returns empty string; strategy router cascades to next fallback.
- **LLM fallback times out**: use fast-path top-1 regardless of margin; log warning; record in trace.
- **Ontology resolver unavailable**: skip pre-annotation; fast path still works.
- **YAML override malformed**: log error, use hardcoded defaults; do not crash bot startup.
- **Cache eviction during concurrent request**: idempotent — recomputation is safe.
- **Store raises exception**: tag that store as unavailable for the request, retry with next-ranked store or apply fallback policy.

---

## Capabilities

### New Capabilities
- `store-router`: per-query store selection layer (fast-path rules + LLM fallback + ontology signal + LRU cache + configurable no-match policy).
- `store-router-config`: Pydantic config schema + YAML override loader.
- `store-routing-trace`: trace entries for observability (which stores considered, scores, path taken, cache hit).

### Modified Capabilities
- `intent-router` (existing, from FEAT-070): exposes hook point so `StoreRouter` can attach to `_run_vector_search` without breaking existing behavior.
- `abstract-bot-vector-context` (existing): `_build_vector_context()` becomes router-aware when `StoreRouter` is configured.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/abstract.py` (`_build_vector_context`, line 2129) | modifies | Adds router-aware branch; backward-compat flag keeps default path unchanged when router not configured. |
| `parrot/bots/mixins/intent_router.py` | extends | Extract LLM-route prompt/parse helpers into shared utility; add hook for store-router attachment. |
| `parrot/registry/routing/store_router.py` | creates | New module: `StoreRouter`, `StoreRouterConfig`, `StoreRoutingDecision`, `StoreFallbackPolicy`. |
| `parrot/tools/multistoresearch.py` | depends on | Used as the `FAN_OUT` fallback implementation. |
| `parrot/knowledge/ontology/intent.py` | depends on | `OntologyIntentResolver` used as pre-annotator signal source. |
| `parrot/stores/abstract.py` | depends on | Unified `similarity_search` interface used verbatim. |
| Agent YAML configs | extends | New optional `store_router:` section with rules and policy. |

No new external dependencies. No breaking changes to bots that don't configure the router.

---

## Code Context

### User-Provided Code
_None — specification driven by conversation._

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/bots/mixins/intent_router.py:106
class IntentRouterMixin:
    _router_active: bool  # line 120
    _router_config: Optional[IntentRouterConfig]  # line 121
    _capability_registry: Optional[CapabilityRegistry]  # line 122

    def configure_router(
        self,
        config: IntentRouterConfig,
        registry: CapabilityRegistry,
    ) -> None: ...  # line 137

    async def conversation(self, prompt: str, **kwargs: Any) -> Any: ...  # line 154

    async def _route(
        self, prompt: str
    ) -> tuple[Optional[str], Optional[RoutingDecision], Optional[RoutingTrace]]: ...  # line 188

    def _fast_path(
        self,
        prompt: str,
        strategies: list[RoutingType],
        candidates: list[RouterCandidate],
    ) -> Optional[RoutingDecision]: ...  # line 320

    async def _llm_route(
        self,
        prompt: str,
        strategies: list[RoutingType],
        candidates: list[RouterCandidate],
    ) -> Optional[RoutingDecision]: ...  # line 361

    async def _run_vector_search(
        self,
        prompt: str,
        candidates: list[RouterCandidate],
    ) -> Optional[str]: ...  # line 709

# From parrot/registry/capabilities/models.py:25
class RoutingType(str, Enum):
    GRAPH_PAGEINDEX = "graph_pageindex"
    DATASET = "dataset"
    VECTOR_SEARCH = "vector_search"
    TOOL_CALL = "tool_call"
    FREE_LLM = "free_llm"
    MULTI_HOP = "multi_hop"
    FALLBACK = "fallback"
    HITL = "hitl"

# From parrot/registry/capabilities/models.py:131
class IntentRouterConfig(BaseModel):
    confidence_threshold: float = 0.7  # line 151
    hitl_threshold: float = 0.3  # line 157
    strategy_timeout_s: float = 30.0  # line 163
    exhaustive_mode: bool = False  # line 168
    max_cascades: int = 3  # line 172
    custom_keywords: dict[str, str]  # line 178 — per-agent YAML override precedent

# From parrot/stores/abstract.py:17
class AbstractStore(ABC):
    @abstractmethod
    async def similarity_search(
        self,
        query: str,
        collection: Union[str, None] = None,
        limit: int = 2,
        similarity_threshold: float = 0.0,
        search_strategy: str = "auto",
        metadata_filters: Union[dict, None] = None,
        **kwargs
    ) -> list: ...  # line 162

# From parrot/bots/abstract.py:2129
async def _build_vector_context(
    self,
    question: str,
    use_vectors: bool = True,
    search_type: str = 'similarity',
    search_kwargs: dict = None,
    ensemble_config: dict = None,
    metric_type: str = 'COSINE',
    limit: int = 10,
    score_threshold: float = None,
    return_sources: bool = True,
) -> Tuple[str, Dict[str, Any]]: ...

# From parrot/tools/multistoresearch.py:30
class StoreType(Enum):
    PGVECTOR = "pgvector"
    FAISS = "faiss"
    ARANGO = "arango"

# From parrot/tools/multistoresearch.py:42
class MultiStoreSearchTool(AbstractTool):
    def __init__(
        self,
        pgvector_store: Optional[PgVectorStore] = None,
        faiss_store: Optional[Any] = None,
        arango_store: Optional[ArangoDBStore] = None,
        k: int = 10,
        k_per_store: int = 20,
        bm25_weights: Optional[Dict[str, float]] = None,
        enable_stores: Optional[List[StoreType]] = None,
        **kwargs,
    ): ...  # line 53

    async def _execute(
        self, query: str, k: Optional[int] = None, **kwargs
    ) -> List[Dict[str, Any]]: ...  # line 291

# From parrot/knowledge/ontology/intent.py:48
class OntologyIntentResolver:
    """Soft-deprecated for strategy routing. Repurposed as pre-annotator for store routing."""
    # Two-path: fast keyword scan, LLM fallback. See lines 53-75.
```

#### Verified Imports
```python
from parrot.bots.mixins.intent_router import IntentRouterMixin  # parrot/bots/mixins/__init__.py
from parrot.registry.capabilities.models import (
    IntentRouterConfig, RoutingType, RoutingDecision, RouterCandidate, RoutingTrace, TraceEntry,
)  # parrot/registry/capabilities/__init__.py
from parrot.registry.capabilities.registry import CapabilityRegistry
from parrot.stores.abstract import AbstractStore
from parrot.stores.postgres import PgVectorStore
from parrot.stores.arango import ArangoDBStore
from parrot.stores.faiss_store import FAISSStore  # may raise ImportError — already handled in multistoresearch
from parrot.tools.multistoresearch import MultiStoreSearchTool, StoreType
from parrot.knowledge.ontology import OntologyIntentResolver, OntologyRAGMixin
```

#### Key Attributes & Constants
- `IntentRouterMixin._router_active: bool` — `parrot/bots/mixins/intent_router.py:120`
- `IntentRouterMixin._router_config: IntentRouterConfig | None` — line 121
- `IntentRouterConfig.custom_keywords: dict[str, str]` — precedent for per-agent YAML override (models.py:178)
- `StoreType` enum values: `"pgvector"`, `"faiss"`, `"arango"` — multistoresearch.py:30
- `_KEYWORD_STRATEGY_MAP` — strategy-level keyword map precedent, intent_router.py:42

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/rag/` package~~ — directory does not exist anywhere in the codebase.
- ~~`RAGPipeline` class~~ — no such class.
- ~~`RAGRouter` class~~ — no such class (strategy router is named `IntentRouterMixin`).
- ~~`BaseRetriever` ABC~~ — no such class; `AbstractStore.similarity_search` is the unified interface.
- ~~`DenseRetriever`, `SparseRetriever`, `GraphRetriever`~~ — none of these classes exist.
- ~~`parrot.rag.BaseRetriever` import path~~ — import will fail.
- ~~`StoreRouter` class~~ — does not exist yet (this feature creates it).
- ~~`StoreRouterConfig`, `StoreRoutingDecision`, `StoreFallbackPolicy`~~ — do not exist yet (introduced by this feature).
- ~~`configure_store_router()` method~~ — does not exist yet.
- ~~Feature ID `FEAT-004`~~ — has been **reused** by `graphic-panel-display` (commit `165b5860`). The original `sdd/specs/adaptive-rag.spec.md` is an unimplemented draft that was never added to `.index.json`. This new feature should claim a fresh ID (proposed: **FEAT-111**).

---

## Parallelism Assessment

- **Internal parallelism**: Medium. The feature decomposes into:
  1. `StoreRouterConfig` Pydantic models + YAML loader (independent).
  2. `StoreRouter` fast-path rules engine (independent, depends on config models).
  3. LLM-path extraction + shared helper refactor in `IntentRouterMixin` (independent).
  4. LRU cache wrapper (independent).
  5. Ontology pre-annotator adapter (depends on 1).
  6. `_build_vector_context` integration (depends on 1–5).
  7. Fallback-policy dispatcher using `MultiStoreSearchTool` (depends on 1, 6).
  8. Tests per component + integration tests (after each).

  Tasks 1–4 can be done in parallel; 5 depends on 1; 6 depends on 1–5; 7 depends on 1, 6. So there's moderate parallelism early on, serial near the end.

- **Cross-feature independence**: Minor conflict risk — touches `parrot/bots/abstract.py` (heavily edited file) and `parrot/bots/mixins/intent_router.py`. No current in-flight spec targets these files (FEAT-110 is in MCP helper handler; other in-progress tasks are NavigatorToolkit refactor). Safe to proceed.

- **Recommended isolation**: `per-spec` — all tasks run sequentially in one worktree.

- **Rationale**: The internal tasks share config models and hook points; merging diverging worktrees across the `AbstractBot` edit would be error-prone. The moderate parallelism (tasks 1–4) can be done as sequential fast-tracked tasks without worktree ceremony.

---

## Open Questions

- [ ] What exact value of margin threshold `Y` between top-1 and top-2 scores should be the default? (Suggest starting at `0.15`, tunable per agent.) — *Owner: Jesus*
- [ ] Should `StoreRoutingDecision` be persisted in `RoutingTrace` (extend `TraceEntry` with a `store_rankings` field), or emitted as a separate trace stream for observability? — *Owner: Jesus*
- [ ] Cache eviction policy: plain LRU (default `maxsize=256`) or TTL-based (e.g., 5 min)? LRU is simpler; TTL helps when store contents change frequently. — *Owner: Jesus*
- [ ] Should the LLM-route helper refactor (pulling `_parse_invoke_response` into a shared utility) be in-scope here, or done as a precursor refactor task? — *Owner: Jesus*
- [ ] Does the YAML override format mirror `custom_keywords` verbatim, or is a richer schema needed (per-store weights, entity-type → store mappings)? — *Owner: Jesus*
- [ ] Should the soft-deprecated `OntologyIntentResolver` be formally un-deprecated for use as a pre-annotator, or should a thin adapter wrap it to avoid leaking deprecation warnings into the router path? — *Owner: Jesus*
