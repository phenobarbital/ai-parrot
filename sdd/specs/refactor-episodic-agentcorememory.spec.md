# Feature Specification: Refactor Episodic + AgentCoreMemory Consolidation

**Feature ID**: FEAT-075
**Date**: 2026-04-02
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.7.0

---

## 1. Motivation & Business Requirements

### Problem Statement

`AgentCoreMemory` (`parrot/memory/core.py`) prototyped several valuable patterns — BM25 hybrid search, `ValueScorer` heuristic scoring, cross-domain routing, and a hot/cold distillation pipeline — but it is **completely orphaned**: zero imports, zero usage anywhere in the codebase. Meanwhile, `EpisodicMemoryStore` (FEAT-045) is the production-wired memory system with proper async patterns, backend abstraction (PgVector + FAISS), Pydantic models, Redis caching, reflection engine, and full integration via mixins into the UnifiedMemoryManager.

Rather than fixing the orphaned `AgentCoreMemory`, we should:
1. Extract its valuable patterns into modular, reusable utilities.
2. Integrate those patterns into the EpisodicMemoryStore ecosystem.
3. Extend backend support (Redis vector store for hot-cache retrieval).
4. Delete `core.py` once all patterns are ported.

### Goals

- **G1**: Port BM25 hybrid search into EpisodicMemoryStore as an optional recall strategy (lexical + semantic fusion).
- **G2**: Port ValueScorer as a pluggable importance-scoring strategy, complementing the existing heuristic importance in `EpisodicMemory`.
- **G3**: Port cross-domain routing into the UnifiedMemoryManager for multi-agent memory sharing.
- **G4**: Add a Redis vector backend (`RedisVectorBackend`) implementing `AbstractEpisodeBackend` for hot-cache vector search (Redis Stack / RediSearch).
- **G5**: Enhance PgVector backend with BM25-assisted hybrid retrieval (tsvector + pgvector fusion).
- **G6**: Delete `core.py` after all patterns are ported and verified.

### Non-Goals (explicitly out of scope)

- Rewriting the EpisodicMemoryStore API surface — we extend, not replace.
- Adding new vector store backends beyond Redis (e.g., Qdrant, Milvus, Chroma).
- Changing the Pydantic data model (`EpisodicMemory`) — additive fields only.
- Modifying the ReflectionEngine or embedding provider.
- Porting the BART summarization/distillation scheduler — EpisodicMemoryStore already has compaction and TTL; distillation is a separate concern if needed later.

---

## 2. Architectural Design

### Overview

Extract three reusable utilities from `AgentCoreMemory`, integrate them as optional strategies within the existing episodic memory architecture, and add a Redis vector backend.

```
EpisodicMemoryStore (orchestrator, enhanced)
├── AbstractEpisodeBackend (strategy pattern)
│   ├── PgVectorBackend (enhanced: hybrid BM25+vector)
│   ├── FAISSBackend (unchanged)
│   └── RedisVectorBackend (NEW — Redis Stack)
├── RecallStrategy (NEW — pluggable search fusion)
│   ├── SemanticOnlyStrategy (current default)
│   └── HybridBM25Strategy (NEW — BM25 + semantic)
├── ImportanceScorer (NEW — pluggable scoring)
│   ├── HeuristicScorer (current logic, extracted)
│   └── ValueScorer (ported from AgentCoreMemory)
├── EpisodeEmbeddingProvider (unchanged)
├── ReflectionEngine (unchanged)
└── EpisodeRedisCache (unchanged)

UnifiedMemoryManager (enhanced)
├── CrossDomainRouter (NEW — multi-agent memory sharing)
├── EpisodicMemoryStore
├── SkillRegistry
├── ConversationMemory
└── ContextAssembler
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `EpisodicMemoryStore` | extends | Add recall_strategy and importance_scorer injection points |
| `AbstractEpisodeBackend` | extends | Add `search_hybrid()` optional method for backends that support it |
| `PgVectorBackend` | modifies | Add tsvector column + hybrid search query |
| `UnifiedMemoryManager` | extends | Add cross-domain routing in `get_context_for_query()` |
| `EpisodicMemory` (model) | extends | Add optional `value_score: float` field |
| `EpisodeRedisCache` | unchanged | Hot cache remains separate from RedisVectorBackend |

### Data Models

```python
# New scoring protocol
class ImportanceScorer(Protocol):
    def score(self, episode: EpisodicMemory) -> float:
        """Return importance score in [0.0, 1.0]."""
        ...

# ValueScorer (ported from core.py)
class ValueScorer:
    """Heuristic-based interaction value assessment."""
    outcome_weight: float = 0.3
    tool_usage_weight: float = 0.2
    query_length_weight: float = 0.1
    response_length_weight: float = 0.2
    feedback_weight: float = 0.3
    threshold: float = 0.4

    def score(self, episode: EpisodicMemory) -> float: ...

# Recall strategy
class RecallStrategy(Protocol):
    async def search(
        self,
        query: str,
        query_embedding: list[float],
        backend: AbstractEpisodeBackend,
        namespace_filter: dict,
        top_k: int = 5,
    ) -> list[EpisodeSearchResult]: ...

# BM25 hybrid
class HybridBM25Strategy:
    """Fuses BM25 lexical scores with semantic similarity."""
    bm25_weight: float = 0.4
    semantic_weight: float = 0.6

    async def search(...) -> list[EpisodeSearchResult]: ...

# Cross-domain routing
class CrossDomainRouter:
    """Routes queries to relevant agent namespaces based on expertise."""
    similarity_threshold: float = 0.5
    cross_domain_decay: float = 0.6

    async def find_relevant_agents(
        self,
        query_embedding: list[float],
        current_agent_id: str,
        embedding_provider: EpisodeEmbeddingProvider,
    ) -> list[str]: ...
```

### New Public Interfaces

```python
# Factory enhancement
EpisodicMemoryStore.create_pgvector(
    ...,
    recall_strategy: RecallStrategy | None = None,
    importance_scorer: ImportanceScorer | None = None,
)

# New factory
EpisodicMemoryStore.create_redis_vector(
    redis_url: str,
    index_name: str = "episodes",
    embedding_dim: int = 384,
    namespace: MemoryNamespace | None = None,
    recall_strategy: RecallStrategy | None = None,
    importance_scorer: ImportanceScorer | None = None,
)

# UnifiedMemoryManager enhancement
UnifiedMemoryManager(
    ...,
    cross_domain_router: CrossDomainRouter | None = None,
)
```

---

## 3. Module Breakdown

### Module 1: ImportanceScorer Abstraction
- **Path**: `parrot/memory/episodic/scoring.py`
- **Responsibility**: Define `ImportanceScorer` protocol. Extract current heuristic logic into `HeuristicScorer`. Port `ValueScorer` from `core.py` adapted to `EpisodicMemory` model.
- **Depends on**: `parrot/memory/episodic/models.py`

### Module 2: RecallStrategy Abstraction + HybridBM25Strategy
- **Path**: `parrot/memory/episodic/recall.py`
- **Responsibility**: Define `RecallStrategy` protocol. Implement `SemanticOnlyStrategy` (wraps current `search_similar` logic). Implement `HybridBM25Strategy` porting BM25 index + fusion logic from `core.py`. BM25 index is lazily built per-namespace.
- **Depends on**: `parrot/memory/episodic/models.py`, `parrot/memory/episodic/backends/base.py`
- **External deps**: `bm25s` (optional, lazy-imported)

### Module 3: RedisVectorBackend
- **Path**: `parrot/memory/episodic/backends/redis_vector.py`
- **Responsibility**: Implement `AbstractEpisodeBackend` using Redis Stack (RediSearch + vector similarity). Supports HNSW index, namespace filtering via tag fields, hybrid BM25+vector via RediSearch FT.SEARCH.
- **Depends on**: `parrot/memory/episodic/backends/base.py`, `parrot/memory/episodic/models.py`
- **External deps**: `redis[hiredis]` (already in project), requires Redis Stack server

### Module 4: PgVector Hybrid Enhancement
- **Path**: `parrot/memory/episodic/backends/pgvector.py` (modify existing)
- **Responsibility**: Add `tsvector` column for full-text search. Implement `search_hybrid()` method combining `ts_rank` with cosine distance. Migration helper for existing tables.
- **Depends on**: Module 2 (RecallStrategy protocol)

### Module 5: CrossDomainRouter
- **Path**: `parrot/memory/unified/routing.py`
- **Responsibility**: Port cross-domain routing logic from `core.py`. Maintains agent expertise embeddings. Finds relevant agent namespaces for a query. Applies decay factor to cross-domain results.
- **Depends on**: `parrot/memory/episodic/embedding.py`, `parrot/memory/unified/models.py`

### Module 6: EpisodicMemoryStore Integration
- **Path**: `parrot/memory/episodic/store.py` (modify existing)
- **Responsibility**: Wire `ImportanceScorer` and `RecallStrategy` into store. Add `recall_strategy` parameter to `recall_similar()`. Use `importance_scorer` in `record_episode()` if provided. Add `create_redis_vector()` factory method.
- **Depends on**: Modules 1, 2, 3

### Module 7: UnifiedMemoryManager Integration
- **Path**: `parrot/memory/unified/manager.py` (modify existing)
- **Responsibility**: Wire `CrossDomainRouter` into `get_context_for_query()`. When router is present, expand search across relevant agent namespaces. Merge and deduplicate cross-domain results.
- **Depends on**: Module 5

### Module 8: Delete core.py + Cleanup
- **Path**: `parrot/memory/core.py` (delete)
- **Responsibility**: Verify all patterns from `core.py` are ported and tested. Remove the file. Update `__init__.py` exports if any. Verify no remaining references.
- **Depends on**: Modules 1–7 fully tested

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_heuristic_scorer_outcomes` | Module 1 | Scores SUCCESS > PARTIAL > FAILURE episodes |
| `test_value_scorer_thresholds` | Module 1 | ValueScorer respects configurable threshold |
| `test_value_scorer_weights` | Module 1 | Weight adjustments change scoring correctly |
| `test_semantic_only_strategy` | Module 2 | SemanticOnlyStrategy delegates to backend.search_similar |
| `test_hybrid_bm25_strategy_fusion` | Module 2 | BM25+semantic scores fuse with correct weights |
| `test_hybrid_bm25_lazy_index` | Module 2 | BM25 index builds lazily on first search |
| `test_redis_vector_store_episode` | Module 3 | Store and retrieve episode from Redis Stack |
| `test_redis_vector_search_similar` | Module 3 | Vector similarity search returns ranked results |
| `test_redis_vector_namespace_filter` | Module 3 | Namespace filtering via tag fields |
| `test_redis_vector_graceful_degradation` | Module 3 | Returns empty on connection failure |
| `test_pgvector_hybrid_search` | Module 4 | tsvector + cosine fusion outperforms pure vector |
| `test_pgvector_migration_helper` | Module 4 | Adds tsvector column to existing table without data loss |
| `test_cross_domain_router_finds_agents` | Module 5 | Returns relevant agent IDs above threshold |
| `test_cross_domain_router_decay` | Module 5 | Cross-domain scores are decayed correctly |
| `test_cross_domain_router_excludes_self` | Module 5 | Current agent excluded from results |
| `test_store_with_custom_scorer` | Module 6 | Custom scorer overrides default importance |
| `test_store_with_recall_strategy` | Module 6 | Custom recall strategy used in recall_similar |
| `test_manager_cross_domain_routing` | Module 7 | UnifiedMemoryManager queries multiple agent namespaces |

### Integration Tests

| Test | Description |
|---|---|
| `test_hybrid_search_pgvector_e2e` | Full BM25+vector search against live PgVector |
| `test_redis_vector_backend_e2e` | Full store/search cycle against Redis Stack |
| `test_cross_domain_multi_agent` | Two agents share memories via routing |
| `test_store_to_unified_pipeline` | Episode stored → recalled via UnifiedMemoryManager with routing |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_episodes() -> list[EpisodicMemory]:
    """Episodes across multiple agents/domains for cross-domain testing."""
    ...

@pytest.fixture
def value_scorer() -> ValueScorer:
    return ValueScorer(threshold=0.4)

@pytest.fixture
def hybrid_strategy() -> HybridBM25Strategy:
    return HybridBM25Strategy(bm25_weight=0.4, semantic_weight=0.6)

@pytest.fixture
async def redis_vector_backend(redis_url) -> RedisVectorBackend:
    backend = RedisVectorBackend(redis_url=redis_url)
    await backend.configure()
    yield backend
    await backend.cleanup()
```

---

## 5. Acceptance Criteria

- [ ] `ValueScorer` produces equivalent scores to `AgentCoreMemory._evaluate_interaction_value()` for the same inputs
- [ ] `HybridBM25Strategy` produces fused rankings combining BM25 + semantic scores with configurable weights
- [ ] `RedisVectorBackend` passes all `AbstractEpisodeBackend` protocol tests (store, search_similar, get_recent, get_failures, delete_expired, count)
- [ ] PgVector hybrid search uses `tsvector` + cosine distance with `ts_rank` fusion
- [ ] `CrossDomainRouter` correctly identifies relevant agents and applies decay factor
- [ ] All new components are lazy-import safe (no hard dependency on `bm25s`, `redis`)
- [ ] `core.py` is deleted with zero import breakage
- [ ] All unit tests pass (`pytest tests/unit/memory/ -v`)
- [ ] All integration tests pass where backends are available
- [ ] No breaking changes to existing `EpisodicMemoryStore` or `UnifiedMemoryManager` public API
- [ ] EpisodicMemoryStore default behavior (no scorer/strategy injected) is unchanged

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use `Protocol` (typing) for `ImportanceScorer` and `RecallStrategy` — no ABC needed.
- Lazy-import `bm25s` and `redis` with the existing `lazy_import()` pattern from `core.py`.
- All new classes must be Pydantic `BaseModel` or dataclasses with type hints.
- Async-first: all backend/strategy methods are `async def`.
- Follow existing backend pattern in `faiss.py` / `pgvector.py` for `RedisVectorBackend`.

### Known Risks / Gotchas

- **Redis Stack requirement**: `RedisVectorBackend` requires Redis Stack (RediSearch module), not vanilla Redis. Must document this clearly and handle `MODULE LOAD` errors gracefully.
- **BM25 index memory**: Per-namespace BM25 indexes live in memory. For large episode counts, consider LRU eviction or periodic rebuild.
- **PgVector tsvector migration**: Adding a column to an existing production table requires a migration helper that runs `ALTER TABLE ... ADD COLUMN` and backfills.
- **Cross-domain security**: Routing across agent namespaces could leak information between tenants. The router MUST respect `tenant_id` boundaries.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `bm25s` | `>=0.2.0` | BM25 lexical scoring (optional, lazy-imported) |
| `redis[hiredis]` | `>=5.0` | Already in project; RedisVectorBackend needs Redis Stack server |

---

## 7. Open Questions

- [x] Should `HybridBM25Strategy` maintain its own BM25 index, or should PgVector's `tsvector` be the only BM25 source for that backend? — *Owner: Jesus Lara*: own BM25 index.
- [x] Should `CrossDomainRouter` persist agent expertise embeddings to the database, or compute them on-the-fly from recent episodes? — *Owner: Jesus Lara*: computed on-the-fly for recent episodes.
- [x] Do we need a `RedisVectorBackend` + `EpisodeRedisCache` unification, or should they remain separate (vector search vs. recent-episode cache)? — *Owner: Jesus Lara*: remain separate (vector search vs. recent-episode cache)

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks)
- All 8 modules should be implemented sequentially in dependency order within a single worktree.
- Module 8 (delete core.py) must be last, after all integration tests pass.
- **Cross-feature dependencies**: None — this spec only modifies the memory subsystem, which has no pending specs in-flight.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-02 | Jesus Lara | Initial draft |
