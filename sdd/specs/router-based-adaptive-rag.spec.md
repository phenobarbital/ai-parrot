# Feature Specification: Router-Based Adaptive RAG (Store-Level)

**Feature ID**: FEAT-111
**Date**: 2026-04-20
**Author**: Jesus
**Status**: draft
**Target version**: 0.9.x

> **Source brainstorm**: `sdd/proposals/router-based-adaptive-rag.brainstorm.md`
> **Recommended option**: **Option C** — `StoreRouter` as a sub-layer under `IntentRouterMixin`
> **FEAT-004 note**: the original `sdd/specs/adaptive-rag.spec.md` remains as a historical draft that was never implemented. Its FEAT-ID was reused by `graphic-panel-display`. This spec supersedes the idea under the new identifier **FEAT-111**.

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot has a working **strategy-level** intent router (`IntentRouterMixin`, FEAT-069/070) that selects between `VECTOR_SEARCH`, `GRAPH_PAGEINDEX`, `DATASET`, `TOOL_CALL`, `FREE_LLM`, `MULTI_HOP`, `FALLBACK`, and `HITL`. However, **within** `VECTOR_SEARCH`, there is no routing: `AbstractBot._build_vector_context()` dispatches to a single `self.store`, and the only multi-store option is `MultiStoreSearchTool`, which **always** fans out in parallel across every configured store and reranks with BM25.

This is suboptimal:

- Queries whose shape clearly fits one backend (keyword → PgVector FTS / BM25; graph-shaped → ArangoDB; in-memory prototyping → FAISS) still incur all-stores cost.
- Embedding calls, network round-trips, and rerank overhead pay for retrievals that were never going to matter.
- There is no way to say "prefer PgVector by default; escalate to parallel fan-out only when uncertain."

### Goals

- Add a per-query **store-level router** (`StoreRouter`) that returns a ranked, weighted list of `(StoreType, confidence)` and engages parallel fan-out only when uncertain.
- Reuse `IntentRouterMixin`'s hybrid (heuristic + LLM) pattern rather than build a parallel routing engine.
- Integrate `parrot/knowledge/ontology/` as a **query pre-annotator** that feeds entity/relation signals into routing.
- Make routing decisions **cacheable** (in-memory LRU per bot) and **configurable** (hardcoded defaults + per-agent YAML overrides).
- Implicit activation from `AbstractBot._build_vector_context()` so every RAG-enabled bot benefits once configured.
- Preserve backwards compatibility: unconfigured bots behave exactly as today.

### Non-Goals (explicitly out of scope)

- Replacing `MultiStoreSearchTool` — the Tool remains available and acts as the `FAN_OUT` fallback implementation.
- Replacing `IntentRouterMixin` — `StoreRouter` is strictly a **sub-layer** beneath it.
- Introducing a new `parrot/rag/` package with `BaseRetriever`/`RAGPipeline` abstractions. `AbstractStore.similarity_search()` is already a uniform async interface — no additional wrapper hierarchy is needed.
- Training new embedding models or modifying existing vector store schemas.
- Persistent caching (Redis-backed). In-memory LRU only for this iteration.
- Reactivating the soft-deprecated `OntologyIntentResolver` for strategy routing — it is only reused as a **pre-annotator signal source** under a thin adapter.

---

## 2. Architectural Design

### Overview

`StoreRouter` is a new class activated via `configure_store_router(config)` on bots that already mix in `IntentRouterMixin`. When `IntentRouterMixin` resolves the query to `VECTOR_SEARCH` and the bot subsequently calls `_build_vector_context()`, the router intercepts the dispatch, produces a `StoreRoutingDecision` (ranked list of stores + confidences + trace), and drives the actual retrieval according to the decision. When the top-1 vs top-2 margin falls below a configurable threshold `Y`, the router falls back to parallel fan-out via `MultiStoreSearchTool`'s existing pipeline, per the `StoreFallbackPolicy` the agent selected.

### Component Diagram

```
user query
   │
   ▼
IntentRouterMixin._route()              [existing FEAT-069/070]
   │  (selects VECTOR_SEARCH)
   ▼
IntentRouterMixin._run_vector_search()  [existing — hooks into _build_vector_context]
   │
   ▼
AbstractBot._build_vector_context()     [MODIFIED: router-aware branch]
   │
   ├── (router inactive) ─► self.store.similarity_search()   [today's path]
   │
   └── (router active) ─► StoreRouter.route(query, ctx)      [NEW]
                                │
                                ├── LRU cache lookup
                                ├── OntologyPreAnnotator.annotate(query)
                                ├── fast-path rules (defaults + YAML overrides)
                                ├── margin check (top-1 - top-2 vs Y)
                                │      └─ if uncertain → LLM path via self.invoke()
                                └── StoreRoutingDecision(rankings, fallback_used)
                                         │
                                         ▼
                                StoreRouter.execute(decision)
                                         │
                                         ├── top-N stores (N configurable)
                                         │    └── AbstractStore.similarity_search()
                                         │
                                         └── StoreFallbackPolicy
                                              ├── FAN_OUT → MultiStoreSearchTool._execute()
                                              ├── FIRST_AVAILABLE → first configured store
                                              ├── EMPTY → return ""
                                              └── RAISE → NoSuitableStoreError
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `IntentRouterMixin` (`parrot/bots/mixins/intent_router.py:106`) | extends (via shared helper) | `StoreRouter` reuses the LLM-route prompt/parse pattern. A shared helper is extracted (see Module 3). |
| `IntentRouterConfig` (`parrot/registry/capabilities/models.py:131`) | mirrors | `StoreRouterConfig` follows the same shape, including `custom_keywords`-style YAML override semantics. |
| `AbstractBot._build_vector_context` (`parrot/bots/abstract.py:2129`) | modifies | Adds a router-aware branch, guarded so the unconfigured path is byte-identical to today. |
| `MultiStoreSearchTool` (`parrot/tools/multistoresearch.py:42`) | depends on | Used by the `FAN_OUT` policy to execute the parallel + BM25-rerank pipeline. |
| `AbstractStore.similarity_search` (`parrot/stores/abstract.py:162`) | depends on | Uniform async store interface — no adapter required. |
| `OntologyIntentResolver` (`parrot/knowledge/ontology/intent.py:48`) | wraps (adapter) | Used through `OntologyPreAnnotator` so deprecation warnings stay out of router paths. |
| `StoreType` enum (`parrot/tools/multistoresearch.py:30`) | reuses | Source of truth for `PGVECTOR`, `FAISS`, `ARANGO` identifiers. |

### Data Models

```python
# parrot/registry/routing/models.py (NEW)

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

from parrot.tools.multistoresearch import StoreType  # reuse existing enum


class StoreFallbackPolicy(str, Enum):
    FAN_OUT = "fan_out"
    FIRST_AVAILABLE = "first_available"
    EMPTY = "empty"
    RAISE = "raise"


class StoreRule(BaseModel):
    """One heuristic rule mapping a query pattern to a store + weight."""
    pattern: str = Field(..., description="Lowercase substring or regex (see regex flag)")
    store: StoreType
    weight: float = Field(1.0, ge=0.0, le=1.0)
    regex: bool = False


class StoreRouterConfig(BaseModel):
    """Configuration for StoreRouter — shape mirrors IntentRouterConfig."""
    margin_threshold: float = Field(0.15, ge=0.0, le=1.0,
        description="If top-1 - top-2 < margin, engage LLM fallback")
    confidence_floor: float = Field(0.2, ge=0.0, le=1.0,
        description="Drop stores scoring below this from the decision")
    llm_timeout_s: float = Field(1.0, gt=0.0)
    top_n: int = Field(1, ge=1, description="How many top-ranked stores to query")
    fallback_policy: StoreFallbackPolicy = StoreFallbackPolicy.FAN_OUT
    cache_size: int = Field(256, ge=0, description="0 disables cache")
    enable_ontology_signal: bool = True
    custom_rules: list[StoreRule] = Field(default_factory=list,
        description="Per-agent YAML overrides merged on top of defaults")


class StoreScore(BaseModel):
    store: StoreType
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str = ""


class StoreRoutingDecision(BaseModel):
    rankings: list[StoreScore] = Field(default_factory=list)
    fallback_used: bool = False
    cache_hit: bool = False
    ontology_annotations: Optional[dict] = None
    path: str = Field(..., description="fast | llm | cache | fallback")
    elapsed_ms: float = 0.0
```

### New Public Interfaces

```python
# parrot/registry/routing/store_router.py (NEW)

class StoreRouter:
    """Store-level router. Activated via AbstractBot.configure_store_router()."""

    def __init__(self, config: StoreRouterConfig) -> None: ...

    async def route(
        self,
        query: str,
        available_stores: list[StoreType],
        invoke_fn: Optional[Callable] = None,  # usually bot.invoke
        ontology_resolver: Optional[Any] = None,
    ) -> StoreRoutingDecision: ...

    async def execute(
        self,
        decision: StoreRoutingDecision,
        query: str,
        stores: dict[StoreType, "AbstractStore"],
        multistore_tool: Optional["MultiStoreSearchTool"] = None,
        **search_kwargs,
    ) -> list["SearchResult"]: ...


# parrot/bots/abstract.py (MODIFIED — new method on AbstractBot)
class AbstractBot(...):
    def configure_store_router(self, config: StoreRouterConfig) -> None: ...
    # And _build_vector_context gains a router-aware branch (see Module 6).
```

---

## 3. Module Breakdown

### Module 1: Config & Decision Models
- **Path**: `parrot/registry/routing/models.py` (new)
- **Responsibility**: Pydantic v2 models — `StoreRouterConfig`, `StoreRule`, `StoreScore`, `StoreRoutingDecision`, `StoreFallbackPolicy` enum.
- **Depends on**: `parrot/tools/multistoresearch.py:StoreType` (reused).

### Module 2: YAML Override Loader
- **Path**: `parrot/registry/routing/yaml_loader.py` (new)
- **Responsibility**: `load_store_router_config(path_or_dict)` — merges hardcoded defaults + YAML overrides into a `StoreRouterConfig`; tolerates malformed YAML (logs + returns defaults).
- **Depends on**: Module 1.

### Module 3: Shared LLM-Route Helper Extraction
- **Path**: `parrot/registry/routing/llm_helper.py` (new), minor changes to `parrot/bots/mixins/intent_router.py`.
- **Responsibility**: Extract `_parse_invoke_response`-style JSON-extraction helper and a reusable `run_llm_ranking(invoke_fn, prompt, timeout) -> dict` into a shared utility. `IntentRouterMixin` refactored to use the helper; behavior preserved byte-for-byte.
- **Depends on**: nothing (pure refactor).

### Module 4: Fast-Path Rules Engine
- **Path**: `parrot/registry/routing/rules.py` (new)
- **Responsibility**: `apply_rules(query, rules, available_stores, ontology_annotations) -> list[StoreScore]`. Hardcoded default rules per `StoreType` + user-provided `StoreRule`s applied on top. Default rules to include: keyword-based PgVector preference for short factual queries; ArangoDB preference when ontology annotations list graph-shaped entities; FAISS preference when a configuration flag marks a collection as "prototype" tier.
- **Depends on**: Module 1.

### Module 5: Ontology Pre-Annotator Adapter
- **Path**: `parrot/registry/routing/ontology_signal.py` (new)
- **Responsibility**: Thin adapter wrapping `OntologyIntentResolver` into a `OntologyPreAnnotator.annotate(query) -> dict`. Suppresses deprecation warnings. No-ops cleanly when no ontology is configured.
- **Depends on**: `parrot/knowledge/ontology/intent.py:OntologyIntentResolver`.

### Module 6: LRU Cache Wrapper
- **Path**: `parrot/registry/routing/cache.py` (new)
- **Responsibility**: `DecisionCache(maxsize)` — asyncio-safe LRU over `OrderedDict`, keyed by `(normalized_query_hash, store_fingerprint)`. `cache_size=0` disables.
- **Depends on**: nothing.

### Module 7: `StoreRouter` Core
- **Path**: `parrot/registry/routing/store_router.py` (new)
- **Responsibility**: Orchestration — cache lookup → ontology annotate → fast-path → margin check → optional LLM path → emit `StoreRoutingDecision` → execute according to `top_n` + `StoreFallbackPolicy`.
- **Depends on**: Modules 1, 3, 4, 5, 6 (and `MultiStoreSearchTool` for the `FAN_OUT` policy).

### Module 8: `AbstractBot` Integration
- **Path**: `parrot/bots/abstract.py` (modify — around line 2129 and `__init__`)
- **Responsibility**: Add `configure_store_router(config)` method, store the router on `self._store_router`, and add a router-aware branch inside `_build_vector_context` guarded by `self._store_router is not None`. When the router is not configured, the existing code path is unchanged.
- **Depends on**: Modules 1, 7.

### Module 9: Tracing Extension
- **Path**: `parrot/registry/capabilities/models.py` (modify — extend `TraceEntry` or emit a sibling `StoreTraceEntry`).
- **Responsibility**: Add an optional `store_rankings: list[StoreScore] | None = None` field to `TraceEntry` (additive, default-None — backward compatible), so existing `RoutingTrace` carries store-level detail when available.
- **Depends on**: Module 1.

### Module 10: Tests
- **Path**: `tests/unit/registry/routing/` and `tests/integration/rag/` (new)
- **Responsibility**: Unit tests per module; integration tests against real `PgVectorStore` + `FAISSStore` + `ArangoDBStore`.
- **Depends on**: all other modules.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_store_router_config_defaults` | 1 | `StoreRouterConfig()` validates with sane defaults |
| `test_store_rule_regex_matches` | 1 | `StoreRule(regex=True)` compiles and matches queries |
| `test_store_routing_decision_roundtrip` | 1 | Pydantic serialize/deserialize preserves fields |
| `test_yaml_loader_valid` | 2 | YAML override merges cleanly with defaults |
| `test_yaml_loader_malformed_yaml_falls_back` | 2 | Malformed YAML logs error + returns defaults — does NOT crash |
| `test_llm_helper_parses_valid_json` | 3 | Extracts JSON from AIMessage.output and dicts |
| `test_llm_helper_returns_none_on_unparseable` | 3 | Returns `None` rather than raising |
| `test_intent_router_regression` | 3 | Existing `IntentRouterMixin` tests still pass after refactor |
| `test_rules_prefers_pgvector_for_keyword_query` | 4 | `"what is X"` routes to `PGVECTOR` |
| `test_rules_prefers_arango_with_graph_annotations` | 4 | Ontology annotations with graph entities boost `ARANGO` |
| `test_rules_custom_rule_overrides_default` | 4 | User-provided `StoreRule` takes precedence |
| `test_ontology_adapter_without_resolver` | 5 | Returns empty annotations + no error when ontology absent |
| `test_ontology_adapter_suppresses_deprecation` | 5 | No `DeprecationWarning` leaks into caller |
| `test_cache_lru_eviction` | 6 | Exceeding `maxsize` evicts oldest |
| `test_cache_disabled_when_size_zero` | 6 | `cache_size=0` no-ops |
| `test_router_cache_hit_path` | 7 | Second identical query returns `path="cache"` |
| `test_router_fast_path` | 7 | Clear top-1 skips LLM, returns `path="fast"` |
| `test_router_llm_path_triggered_by_margin` | 7 | Narrow margin invokes `invoke_fn`; `path="llm"` |
| `test_router_llm_timeout_falls_back_to_fast` | 7 | LLM timeout uses fast-path top-1 with trace note |
| `test_router_policy_fan_out` | 7 | `FAN_OUT` policy delegates to `MultiStoreSearchTool` |
| `test_router_policy_first_available` | 7 | Picks first configured store when no confident match |
| `test_router_policy_empty_returns_empty` | 7 | Returns `[]` results; decision flagged `fallback_used=True` |
| `test_router_policy_raise` | 7 | Raises `NoSuitableStoreError` |
| `test_abstractbot_unconfigured_is_unchanged` | 8 | `_build_vector_context` with no router matches pre-change behavior byte-for-byte |
| `test_abstractbot_router_integration` | 8 | `configure_store_router` wires router; subsequent `_build_vector_context` honors rankings |
| `test_trace_entry_carries_store_rankings` | 9 | Additive field preserved through `RoutingTrace` round-trip |

### Integration Tests

| Test | Description |
|---|---|
| `test_router_with_real_pgvector` | Hybrid route against a real PgVector instance (fast-path, LLM-path, cache-hit). |
| `test_router_with_real_arango` | Graph-style queries route to ArangoDB when annotations are present. |
| `test_router_with_multistore_fallback` | Ambiguous query triggers `FAN_OUT` → `MultiStoreSearchTool` executes. |
| `test_router_with_bot_end_to_end` | Full flow: `IntentRouterMixin.conversation → VECTOR_SEARCH → StoreRouter → retrieval → context injection`. |
| `test_perf_fast_path_under_5ms` | Fast path for cached/clear-winner case stays under 5 ms (excluding embedding call). |

### Test Data / Fixtures

```python
@pytest.fixture
def default_store_router_config() -> StoreRouterConfig: ...

@pytest.fixture
def ambiguous_query() -> str:
    return "Tell me something interesting"   # triggers LLM path

@pytest.fixture
def graph_query() -> str:
    return "What are the relationships between suppliers and warehouses?"

@pytest.fixture
def mock_invoke_fn():
    """Returns a coroutine yielding an AIMessage-shaped dict with a ranking."""
```

---

## 5. Acceptance Criteria

- [ ] `from parrot.registry.routing import StoreRouter, StoreRouterConfig, StoreFallbackPolicy` works.
- [ ] A bot that does **not** call `configure_store_router()` behaves byte-identically to today (regression-locked by `test_abstractbot_unconfigured_is_unchanged`).
- [ ] `StoreRouter.route()` returns a `StoreRoutingDecision` with non-empty `rankings` or a `fallback_used=True` flag on every invocation.
- [ ] Fast path completes in < 5 ms for cache hits and clear-winner queries (excluding downstream embedding/retrieval time).
- [ ] LLM path respects `llm_timeout_s` (default 1.0 s); timeouts degrade gracefully to fast-path top-1.
- [ ] Per-agent YAML overrides merge on top of defaults following the same semantics as `IntentRouterConfig.custom_keywords`.
- [ ] `FAN_OUT` policy invokes `MultiStoreSearchTool._execute()` and returns equivalent results to directly invoking the Tool.
- [ ] Routing trace includes store rankings when the router is active.
- [ ] All unit tests pass: `pytest tests/unit/registry/routing/ -v`.
- [ ] All integration tests pass: `pytest tests/integration/rag/ -v`.
- [ ] No `DeprecationWarning` from `OntologyIntentResolver` leaks into router logs.
- [ ] Existing `IntentRouterMixin` test suite continues to pass unmodified after the Module 3 refactor.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Carried forward from `sdd/proposals/router-based-adaptive-rag.brainstorm.md` § Code Context
> and re-verified in this session. Every reference below was confirmed via `read` / `grep`.

### Verified Imports

```python
from parrot.bots.mixins.intent_router import IntentRouterMixin
from parrot.registry.capabilities.models import (
    IntentRouterConfig, RoutingType, RoutingDecision, RouterCandidate,
    RoutingTrace, TraceEntry,
)
from parrot.registry.capabilities.registry import CapabilityRegistry
from parrot.stores.abstract import AbstractStore
from parrot.stores.postgres import PgVectorStore
from parrot.stores.arango import ArangoDBStore
from parrot.stores.faiss_store import FAISSStore   # may ImportError — handle as in multistoresearch.py
from parrot.tools.multistoresearch import MultiStoreSearchTool, StoreType
from parrot.knowledge.ontology import OntologyIntentResolver, OntologyRAGMixin
from parrot.stores.models import SearchResult, Document
```

### Existing Class Signatures

```python
# parrot/bots/mixins/intent_router.py:106
class IntentRouterMixin:
    _router_active: bool                                # line 120
    _router_config: Optional[IntentRouterConfig]        # line 121
    _capability_registry: Optional[CapabilityRegistry]  # line 122

    def __init__(self, **kwargs: Any) -> None: ...      # line 124
    def configure_router(
        self, config: IntentRouterConfig, registry: CapabilityRegistry
    ) -> None: ...                                       # line 137

    async def conversation(self, prompt: str, **kwargs: Any) -> Any: ...   # line 154
    async def _route(
        self, prompt: str
    ) -> tuple[Optional[str], Optional[RoutingDecision], Optional[RoutingTrace]]: ...  # line 188

    def _fast_path(
        self, prompt: str, strategies: list[RoutingType], candidates: list[RouterCandidate]
    ) -> Optional[RoutingDecision]: ...                  # line 320
    async def _llm_route(
        self, prompt: str, strategies: list[RoutingType], candidates: list[RouterCandidate]
    ) -> Optional[RoutingDecision]: ...                  # line 361
    def _parse_invoke_response(
        self, response: Any, available_strategies: list[RoutingType]
    ) -> Optional[RoutingDecision]: ...                  # line 424
    async def _run_vector_search(
        self, prompt: str, candidates: list[RouterCandidate]
    ) -> Optional[str]: ...                              # line 709

# parrot/registry/capabilities/models.py:25
class RoutingType(str, Enum):
    GRAPH_PAGEINDEX = "graph_pageindex"
    DATASET         = "dataset"
    VECTOR_SEARCH   = "vector_search"
    TOOL_CALL       = "tool_call"
    FREE_LLM        = "free_llm"
    MULTI_HOP       = "multi_hop"
    FALLBACK        = "fallback"
    HITL            = "hitl"

# parrot/registry/capabilities/models.py:131
class IntentRouterConfig(BaseModel):
    confidence_threshold: float = 0.7   # line 151
    hitl_threshold:       float = 0.3   # line 157
    strategy_timeout_s:   float = 30.0  # line 163
    exhaustive_mode:      bool  = False # line 168
    max_cascades:         int   = 3     # line 172
    custom_keywords:      dict[str, str]  # line 178  — precedent for YAML overrides

# parrot/stores/abstract.py:17
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
        **kwargs,
    ) -> list: ...                      # line 162

# parrot/bots/abstract.py:2129
class AbstractBot(...):
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

# parrot/tools/multistoresearch.py:30
class StoreType(Enum):
    PGVECTOR = "pgvector"
    FAISS    = "faiss"
    ARANGO   = "arango"

# parrot/tools/multistoresearch.py:42
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
    ): ...                                               # line 53

    async def _execute(
        self, query: str, k: Optional[int] = None, **kwargs
    ) -> List[Dict[str, Any]]: ...                       # line 291

# parrot/knowledge/ontology/intent.py:48
class OntologyIntentResolver:
    """Soft-deprecated for strategy routing; reused here only as a signal source via an adapter."""
    __deprecated__ = True                                # line 77
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `StoreRouter` | `AbstractBot._build_vector_context()` | router-aware branch | `parrot/bots/abstract.py:2129` |
| `StoreRouter` | `AbstractStore.similarity_search()` | direct call per ranked store | `parrot/stores/abstract.py:162` |
| `StoreRouter` (FAN_OUT policy) | `MultiStoreSearchTool._execute()` | delegated call | `parrot/tools/multistoresearch.py:291` |
| `OntologyPreAnnotator` | `OntologyIntentResolver.resolve_intent()` (or equivalent) | adapter | `parrot/knowledge/ontology/intent.py:48` |
| `StoreRouter.route()` LLM path | `bot.invoke()` | callable reference | `IntentRouterMixin._llm_route` line 361 — same contract |
| `StoreRouterConfig.custom_rules` | YAML file | `load_store_router_config()` | mirrors `IntentRouterConfig.custom_keywords` (models.py:178) |
| `TraceEntry.store_rankings` (new optional field) | `RoutingTrace.entries` | additive Pydantic field | `parrot/registry/capabilities/models.py:99` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/rag/` package~~ — directory does not exist.
- ~~`RAGPipeline`, `RAGRouter`, `BaseRetriever`, `DenseRetriever`, `SparseRetriever`, `GraphRetriever` classes~~ — none of these exist anywhere in the codebase. Do NOT import them.
- ~~`from parrot.rag import ...`~~ — any such import will fail.
- ~~`StoreRouter`, `StoreRouterConfig`, `StoreRoutingDecision`, `StoreFallbackPolicy`, `StoreScore`, `StoreRule`, `OntologyPreAnnotator`, `DecisionCache`~~ — do not exist yet; this feature introduces them.
- ~~`AbstractBot.configure_store_router()`~~ — does not exist yet.
- ~~`AbstractBot._store_router` attribute~~ — does not exist yet.
- ~~`TraceEntry.store_rankings`~~ — new optional field introduced by Module 9; defaults to `None`.
- ~~Feature ID FEAT-004 for adaptive-rag~~ — reused by `graphic-panel-display` (commit `165b5860`). The legacy `sdd/specs/adaptive-rag.spec.md` is a historical draft only.
- ~~`functools.lru_cache` used directly on async methods~~ — avoid; use the `DecisionCache` wrapper (Module 6) built on `OrderedDict` + `asyncio.Lock`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Async-first**: every router/adapter method is `async` unless it is pure / deterministic.
- **Pydantic v2** for all config, rules, and decision models.
- **Logging**: `self.logger` (never `print`). DEBUG for per-step routing detail; INFO for decisions; WARNING on LLM timeouts and malformed YAML.
- **Config override semantics**: hardcoded defaults → merged with per-agent YAML → same precedence rule as `IntentRouterConfig.custom_keywords` (models.py:178).
- **MRO**: `StoreRouter` is **not** a mixin. It is an owned object (`self._store_router`) on the bot, assigned by `configure_store_router(config)`. This avoids MRO surprises on top of the already-complex `IntentRouterMixin` chain.
- **Backwards compatibility**: `_build_vector_context` begins with `if self._store_router is None: <existing body>` — the unconfigured path is untouched.
- **Shared helper (Module 3)**: keep extraction surgical. Verify `test_intent_router_regression` passes before proceeding to Module 7.

### Known Risks / Gotchas

- **`functools.lru_cache` on async methods** silently returns coroutine wrappers that get cached but never awaited a second time — do NOT use it. Use `DecisionCache` (Module 6).
- **`OntologyIntentResolver` emits a `DeprecationWarning`** via `warnings.warn` — the adapter must filter or suppress it so router logs stay clean.
- **FAISSStore import may fail** in environments without FAISS installed — follow the existing pattern in `multistoresearch.py:24-27` (`try/except ImportError`).
- **Ambiguity with `IntentRouterMixin.exhaustive_mode=True`**: when the strategy router already runs all strategies, the store router should still narrow inside `VECTOR_SEARCH` — add an explicit unit test.
- **Cache key normalization**: lowercase + collapse whitespace + strip punctuation. Document the normalization in a docstring so it is reproducible in tests.
- **LLM path cost**: the fallback prompt should be small and focused (list of store types, ontology annotations, query). Budget ≤ 400 tokens input / ≤ 100 output.
- **Store fingerprint for cache key**: include (sorted tuple of available stores + their collection names) so a config change invalidates stale decisions.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.0` | already project-wide; used for config and decision models |
| `pyyaml` | `>=6.0` | already project-wide; YAML override loader |
| `bm25s` / `rank-bm25` | existing | reused via `MultiStoreSearchTool` for `FAN_OUT` fallback |
| (no new deps) | — | — |

---

## 8. Open Questions

- [ ] Default `margin_threshold` value — proposing `0.15`. Confirm or tune after first integration test. — *Owner: Jesus*
- [ ] Cache eviction policy — plain LRU (`maxsize=256`) for v1; TTL consideration deferred to follow-up if store contents change frequently. — *Owner: Jesus*
- [ ] Exact YAML override schema — minimal (`custom_rules` list of `StoreRule`) for v1 vs. richer (per-store weights, entity-type → store mapping). Ship minimal; iterate. — *Owner: Jesus*
- [ ] Whether Module 3 (shared LLM helper extraction) should land as a precursor PR on its own, or bundle in this feature. Proposal: bundle, since regression-test coverage on `IntentRouterMixin` catches issues. — *Owner: Jesus*
- [ ] Should `OntologyIntentResolver` be formally un-deprecated given its reuse here? Proposal: keep the soft-deprecation for strategy routing; document that store routing uses it internally via an adapter. — *Owner: Jesus*
- [ ] Should the tracing extension (Module 9) be released in this feature or split into a follow-up observability feature? Proposal: keep in-scope; it is a single additive field. — *Owner: Jesus*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`.
- **Rationale**: Modules share config models and hook points, and several modules converge on the same edits in `parrot/bots/abstract.py` and `parrot/bots/mixins/intent_router.py`. Merging divergent worktrees across those files would be error-prone. Moderate internal parallelism exists (Modules 1, 2, 3, 6 are largely independent), but since these are small modules the sequential-in-one-worktree model keeps integration straightforward.
- **Cross-feature dependencies**: None. FEAT-110 (`mcp-mixin-helper-handler`) is in progress but does not touch `parrot/bots/abstract.py`, `parrot/bots/mixins/intent_router.py`, `parrot/registry/`, `parrot/tools/multistoresearch.py`, or `parrot/knowledge/ontology/`. Safe to proceed in parallel with other in-flight features.
- **Suggested worktree creation (after task decomposition)**:
  ```
  git worktree add -b feat-111-router-based-adaptive-rag \
    .claude/worktrees/feat-111-router-based-adaptive-rag HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-20 | Jesus | Initial draft — scaffolded from `router-based-adaptive-rag.brainstorm.md` (Recommended Option C). |
