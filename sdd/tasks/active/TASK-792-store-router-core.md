# TASK-792: StoreRouter Core Orchestrator

**Feature**: FEAT-111 — Router-Based Adaptive RAG (Store-Level)
**Spec**: `sdd/specs/router-based-adaptive-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-785, TASK-786, TASK-787, TASK-788, TASK-789, TASK-790, TASK-791
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** of FEAT-111 — the heart of the feature. This class orchestrates all the pieces created by prior tasks into the end-to-end store-routing decision + execution flow.

---

## Scope

- Create `parrot/registry/routing/store_router.py` with `class StoreRouter`:
  - `__init__(self, config: StoreRouterConfig, ontology_resolver: Optional[Any] = None) -> None` — stores config, constructs a `DecisionCache(config.cache_size)`, wraps `ontology_resolver` in an `OntologyPreAnnotator`.
  - `async def route(self, query: str, available_stores: list[StoreType], invoke_fn: Optional[Callable] = None) -> StoreRoutingDecision`:
    1. Build cache key using `build_cache_key(query, sorted store fingerprint)`.
    2. Cache lookup — hit → return the cached decision with `cache_hit=True` and `path="cache"`.
    3. Ontology annotate (if `enable_ontology_signal`).
    4. Fast path — `apply_rules(query, merged_rules, available_stores, annotations)`.
    5. If rankings empty → fall through to fallback assembly (below).
    6. Margin check — if `(top1 - top2) < config.margin_threshold` AND `invoke_fn` is provided → LLM path.
    7. LLM path: construct a small prompt (store list + annotations + query + schema), call `run_llm_ranking(invoke_fn, prompt, config.llm_timeout_s)`, merge the LLM output with fast-path scores via weighted average (0.5/0.5 unless config says otherwise for v1 keep 0.5/0.5).
    8. Drop entries whose confidence falls below `config.confidence_floor`.
    9. Assemble `StoreRoutingDecision`. Populate `path` as `"cache" | "fast" | "llm" | "fallback"`. Populate `ontology_annotations`. Populate `elapsed_ms`. Populate `fallback_used=True` when rankings end up empty.
    10. Cache the decision (unless it's a cache-hit decision).
  - `async def execute(self, decision: StoreRoutingDecision, query: str, stores: dict[StoreType, AbstractStore], multistore_tool: Optional[MultiStoreSearchTool] = None, **search_kwargs) -> list[SearchResult]`:
    1. If `decision.fallback_used` → apply `StoreFallbackPolicy`:
       - `FAN_OUT`: delegate to `multistore_tool._execute(query, **search_kwargs)` if provided; else run parallel `similarity_search` across `stores.values()` and concatenate.
       - `FIRST_AVAILABLE`: pick `next(iter(stores.values()))` (insertion-ordered) and run one search.
       - `EMPTY`: return `[]`.
       - `RAISE`: raise `NoSuitableStoreError`.
    2. Otherwise: pick top-`config.top_n` stores from `decision.rankings`, call their `similarity_search` concurrently, return concatenated results (deduplication is the caller's responsibility — keep this method focused).
- Add a `class NoSuitableStoreError(RuntimeError)` in the same module.
- Unit tests under `tests/unit/registry/routing/test_store_router.py` covering cache/fast/llm paths and all four fallback policies, using a fake `invoke_fn` and fake stores.

**NOT in scope**: `AbstractBot` integration (TASK-793), integration tests with real stores (TASK-794).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/routing/store_router.py` | CREATE | `StoreRouter`, `NoSuitableStoreError` |
| `packages/ai-parrot/src/parrot/registry/routing/__init__.py` | MODIFY | Re-export `StoreRouter`, `NoSuitableStoreError` |
| `packages/ai-parrot/tests/unit/registry/routing/test_store_router.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio
import time
import logging
from typing import Any, Callable, Optional

from parrot.registry.routing import (
    StoreRouterConfig, StoreRoutingDecision, StoreScore, StoreRule,
    StoreFallbackPolicy, DecisionCache, build_cache_key,
    apply_rules, DEFAULT_STORE_RULES, OntologyPreAnnotator,
    extract_json_from_response, run_llm_ranking,
)
from parrot.tools.multistoresearch import StoreType, MultiStoreSearchTool  # multistoresearch.py:30, 42
from parrot.stores.abstract import AbstractStore                            # stores/abstract.py:17
from parrot.stores.models import SearchResult                               # see multistoresearch.py line 18
```

### Existing Signatures to Use
```python
# parrot/stores/abstract.py:162
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
    ) -> list: ...

# parrot/tools/multistoresearch.py:42
class MultiStoreSearchTool(AbstractTool):
    async def _execute(self, query: str, k: Optional[int] = None, **kwargs) -> List[Dict[str, Any]]:
        ...   # line 291
```

### Does NOT Exist
- ~~`AbstractStore.search`~~ — the method is `similarity_search`.
- ~~A ready-made `RouterExecutor`~~ — `StoreRouter.execute` is the executor.
- ~~Deduplication of results across stores~~ — not this task's responsibility. The bot or downstream consumer handles it (as it does today via `MultiStoreSearchTool._deduplicate_results`).

---

## Implementation Notes

### LLM prompt skeleton (keep small — spec §7 says ≤ 400 tokens in / ≤ 100 out)
```
You are a retrieval router. Available stores: {store_list}.
Query: "{query}"
Ontology annotations: {annotations or "none"}
Respond with JSON:
{"rankings": [{"store": "<name>", "confidence": <0-1>, "reason": "<short>"}]}
```

### Key Constraints
- `asyncio.gather(*similarity_calls)` for top-N parallel fetches; use `return_exceptions=True` and drop failed stores with a WARNING log.
- `elapsed_ms` measured via `time.monotonic()` at start and end of `route()`.
- Never block the event loop; all retrieval paths are `async`.
- The router does NOT own the stores — callers pass the `stores` dict to `execute()`. This keeps `StoreRouter` decoupled from bot lifecycle.
- When `invoke_fn` is `None` (bot has no LLM) and the margin is tight → skip LLM path, use fast-path top-1 with a WARNING note in `decision.path` (`"fast"` still — don't invent a new path).
- Merge strategy for LLM-path scores: for each store, `final = 0.5 * fast_score + 0.5 * llm_score`. Stores present in one list but not the other use their only score.
- `rankings` must always be sorted descending by confidence before returning.
- Cache `put` happens AFTER the decision is fully assembled; cache hits short-circuit at step 2.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py:188` — `_route` general shape (fast → LLM → trace)
- `packages/ai-parrot/src/parrot/tools/multistoresearch.py:291` — `_execute` pattern for the `FAN_OUT` fallback

---

## Acceptance Criteria

- [ ] `from parrot.registry.routing import StoreRouter, NoSuitableStoreError` works.
- [ ] Cache hit path: second call with identical query + same `available_stores` returns `cache_hit=True` and `path="cache"`.
- [ ] Fast path: wide-margin query returns `path="fast"` and does NOT call `invoke_fn`.
- [ ] LLM path: tight-margin query calls `invoke_fn` once; returns `path="llm"`; respects `llm_timeout_s`.
- [ ] LLM timeout: `invoke_fn` that sleeps past `llm_timeout_s` → falls back to fast-path top-1; does NOT raise.
- [ ] `FAN_OUT` policy: empty rankings → delegates to `multistore_tool._execute`; if `multistore_tool is None` → parallel `similarity_search` across all stores.
- [ ] `FIRST_AVAILABLE` policy: empty rankings → first store's `similarity_search` only.
- [ ] `EMPTY` policy: empty rankings → returns `[]`.
- [ ] `RAISE` policy: empty rankings → raises `NoSuitableStoreError`.
- [ ] `execute()` with non-empty rankings: runs top-N searches concurrently.
- [ ] `elapsed_ms` is populated and non-negative.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/unit/registry/routing/test_store_router.py -v`.

---

## Test Specification

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.registry.routing import (
    StoreRouter, StoreRouterConfig, StoreFallbackPolicy,
    NoSuitableStoreError,
)
from parrot.tools.multistoresearch import StoreType


@pytest.fixture
def fake_stores():
    s = {}
    for t in (StoreType.PGVECTOR, StoreType.FAISS, StoreType.ARANGO):
        m = AsyncMock()
        m.similarity_search = AsyncMock(return_value=[])
        s[t] = m
    return s


@pytest.fixture
def config():
    return StoreRouterConfig(
        margin_threshold=0.1,
        fallback_policy=StoreFallbackPolicy.EMPTY,
        cache_size=8,
    )


@pytest.mark.asyncio
async def test_fast_path(config, fake_stores):
    router = StoreRouter(config)
    decision = await router.route(
        "what is an endcap?", list(fake_stores.keys()), invoke_fn=None
    )
    assert decision.path == "fast"
    assert decision.rankings[0].store == StoreType.PGVECTOR


@pytest.mark.asyncio
async def test_cache_hit(config, fake_stores):
    router = StoreRouter(config)
    q = "graph relationships between suppliers"
    d1 = await router.route(q, list(fake_stores.keys()), invoke_fn=None)
    d2 = await router.route(q, list(fake_stores.keys()), invoke_fn=None)
    assert d2.cache_hit is True
    assert d2.path == "cache"
    assert d1.rankings[0].store == d2.rankings[0].store


@pytest.mark.asyncio
async def test_llm_path_triggered_by_tight_margin():
    cfg = StoreRouterConfig(margin_threshold=0.9)   # almost always tight
    router = StoreRouter(cfg)
    calls = []
    async def fake_invoke(prompt):
        calls.append(prompt)
        class M: output = {"rankings": [{"store": "arango", "confidence": 0.95, "reason": "x"}]}
        return M()
    decision = await router.route(
        "ambiguous query", list(StoreType), invoke_fn=fake_invoke
    )
    assert len(calls) == 1
    assert decision.path == "llm"


@pytest.mark.asyncio
async def test_llm_timeout_falls_back_to_fast():
    cfg = StoreRouterConfig(margin_threshold=0.9, llm_timeout_s=0.05)
    router = StoreRouter(cfg)
    async def slow(prompt):
        await asyncio.sleep(5)
    decision = await router.route("anything", list(StoreType), invoke_fn=slow)
    assert decision.path == "fast"


@pytest.mark.asyncio
async def test_fan_out_policy_delegates(config, fake_stores):
    cfg = StoreRouterConfig(fallback_policy=StoreFallbackPolicy.FAN_OUT)
    router = StoreRouter(cfg)
    tool = MagicMock()
    tool._execute = AsyncMock(return_value=[{"content": "x"}])
    # craft an empty-rankings decision via an unmatched query
    decision = await router.route("zzzzzz", [StoreType.PGVECTOR], invoke_fn=None)
    decision.fallback_used = True
    decision.rankings = []
    results = await router.execute(decision, "zzzzzz", fake_stores, multistore_tool=tool)
    tool._execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_policy(fake_stores):
    cfg = StoreRouterConfig(fallback_policy=StoreFallbackPolicy.EMPTY)
    router = StoreRouter(cfg)
    decision = await router.route("zzzzzz", [StoreType.PGVECTOR], invoke_fn=None)
    decision.fallback_used = True
    decision.rankings = []
    results = await router.execute(decision, "zzzzzz", fake_stores)
    assert results == []


@pytest.mark.asyncio
async def test_raise_policy(fake_stores):
    cfg = StoreRouterConfig(fallback_policy=StoreFallbackPolicy.RAISE)
    router = StoreRouter(cfg)
    decision = await router.route("zzzzzz", [StoreType.PGVECTOR], invoke_fn=None)
    decision.fallback_used = True
    decision.rankings = []
    with pytest.raises(NoSuitableStoreError):
        await router.execute(decision, "zzzzzz", fake_stores)


@pytest.mark.asyncio
async def test_execute_top_n_concurrent(fake_stores):
    cfg = StoreRouterConfig(top_n=2)
    router = StoreRouter(cfg)
    decision = await router.route("relationship between", list(StoreType), invoke_fn=None)
    await router.execute(decision, "relationship between", fake_stores)
    # At least the top-ranked store was queried.
    called = sum(1 for s in fake_stores.values() if s.similarity_search.await_count > 0)
    assert 1 <= called <= cfg.top_n
```

---

## Agent Instructions

1. Read the spec (§2 Architectural Design Overview + Component Diagram; §3 Module 7; §7 all constraints).
2. Verify every dependency task is in `sdd/tasks/completed/`: TASK-785, 786, 787, 788, 789, 790, 791.
3. Re-verify that `AbstractStore.similarity_search` signature has not drifted (`parrot/stores/abstract.py:162`).
4. Implement `StoreRouter` + `NoSuitableStoreError`.
5. Run the test suite.
6. Move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*
