# TASK-794: End-to-End Integration Tests

**Feature**: FEAT-111 — Router-Based Adaptive RAG (Store-Level)
**Spec**: `sdd/specs/router-based-adaptive-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-785, TASK-786, TASK-787, TASK-788, TASK-789, TASK-790, TASK-791, TASK-792, TASK-793
**Assigned-to**: unassigned

---

## Context

Implements **Module 10** (integration tier) of FEAT-111. Unit tests have already been placed next to each module; this task rounds out the test suite with integration tests that exercise the full pipeline against real or realistic fakes of the stores, plus the performance budget check.

---

## Scope

- Create `tests/integration/rag/test_store_router_integration.py` with the five scenarios listed in spec §4 Integration Tests:
  1. `test_router_with_real_pgvector` — fast-path, LLM-path, and cache-hit paths against a real (or test-container-backed) `PgVectorStore`.
  2. `test_router_with_real_arango` — graph-style queries with ontology annotations route to ArangoDB.
  3. `test_router_with_multistore_fallback` — ambiguous query triggers `FAN_OUT` → `MultiStoreSearchTool` delivers deduped results.
  4. `test_router_with_bot_end_to_end` — full flow via `IntentRouterMixin.conversation → VECTOR_SEARCH → _build_vector_context → StoreRouter`.
  5. `test_perf_fast_path_under_5ms` — fast path (cache-hit AND clear-winner) stays under 5 ms (excluding downstream embedding / retrieval). Use `time.perf_counter()` around `StoreRouter.route()` only.
- If a store is not available in the test environment, `pytest.skip()` with a clear reason. Do NOT fail hard.
- Reuse existing test fixtures where they exist (look in `tests/integration/` and `tests/conftest.py`).

**NOT in scope**: unit tests (covered by prior tasks), performance tuning of the router, new fixtures for stores that aren't already wired up for integration testing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/rag/__init__.py` | CREATE | Test package init (may already exist — check first) |
| `packages/ai-parrot/tests/integration/rag/test_store_router_integration.py` | CREATE | Five integration scenarios |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio
import time
import pytest

from parrot.registry.routing import (
    StoreRouter, StoreRouterConfig, StoreFallbackPolicy,
)
from parrot.tools.multistoresearch import MultiStoreSearchTool, StoreType
from parrot.stores.postgres import PgVectorStore    # real store
from parrot.stores.arango import ArangoDBStore      # real store
try:
    from parrot.stores.faiss_store import FAISSStore
except ImportError:
    FAISSStore = None
```

### Existing Signatures to Use
```python
# Reused from prior tasks — re-verify signatures in the modules they were created by.
StoreRouter.__init__(config, ontology_resolver=None)
StoreRouter.route(query, available_stores, invoke_fn=None) -> StoreRoutingDecision
StoreRouter.execute(decision, query, stores, multistore_tool=None, **search_kwargs) -> list
```

### Does NOT Exist
- ~~A global `pytest` fixture `integration_pgvector`~~ — check existing conftest; reuse only what is present.
- ~~A benchmark harness module~~ — simple `time.perf_counter()` is sufficient for the 5ms budget.

---

## Implementation Notes

### Skipping when environment is incomplete
Wrap each integration test with a fixture that attempts to connect to the real store at module scope. If connection fails, raise `pytest.skip("PgVector not available in this environment")` in the fixture. Tests that don't need that store run normally.

### Performance test caveat
- `time.perf_counter()` around `await router.route(...)` ONLY. Do NOT include `execute()` (store I/O) in the measurement.
- Pre-warm the cache with one call, THEN measure. The budget applies to the router's own work, not to the downstream retrieval.
- Run the measured call at least 5 times; assert the median (not the max) < 5 ms to tolerate GC / scheduling jitter.

### End-to-end bot test
Construct a minimal `AbstractBot` subclass or reuse an existing test bot (check `tests/unit/bots/` for fixtures), attach `IntentRouterMixin` + `configure_router()` + `configure_store_router()`, then feed a query through `conversation()` and assert the trace includes `store_rankings`.

### References in Codebase
- Existing integration tests under `packages/ai-parrot/tests/integration/` — use as style reference (look for `test_*_integration.py` patterns).
- `packages/ai-parrot/src/parrot/tools/multistoresearch.py:291` — `_execute` for fan-out fallback.

---

## Acceptance Criteria

- [ ] Five scenarios implemented per spec §4.
- [ ] Each scenario `pytest.skip`s cleanly when its required backend is not available in the environment (no hard failures on developer machines without a full store stack).
- [ ] `test_perf_fast_path_under_5ms` passes locally with median < 5 ms after a warm-up call.
- [ ] `pytest packages/ai-parrot/tests/integration/rag/ -v` passes (or cleanly skips) on CI.
- [ ] No flaky timing tests — the perf budget applies to the median, not the max.

---

## Test Specification

```python
import asyncio, time, pytest
from parrot.registry.routing import (
    StoreRouter, StoreRouterConfig, StoreFallbackPolicy,
)
from parrot.tools.multistoresearch import StoreType, MultiStoreSearchTool


@pytest.fixture(scope="module")
def pgvector_store():
    try:
        # construct and ping; skip on failure
        from parrot.stores.postgres import PgVectorStore
        store = PgVectorStore(...)   # use project-standard test config
        asyncio.get_event_loop().run_until_complete(store.ping())  # or whichever health-check exists
        return store
    except Exception as exc:
        pytest.skip(f"PgVector unavailable: {exc}")


@pytest.mark.asyncio
async def test_router_with_real_pgvector(pgvector_store):
    router = StoreRouter(StoreRouterConfig(cache_size=8))
    stores = {StoreType.PGVECTOR: pgvector_store}
    # fast path
    d1 = await router.route("what is an endcap?", list(stores.keys()))
    assert d1.path == "fast"
    # cache hit
    d2 = await router.route("what is an endcap?", list(stores.keys()))
    assert d2.cache_hit is True
    # execute returns results (even if empty list for an empty test db)
    results = await router.execute(d1, "what is an endcap?", stores)
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_router_with_multistore_fallback(pgvector_store):
    cfg = StoreRouterConfig(fallback_policy=StoreFallbackPolicy.FAN_OUT)
    router = StoreRouter(cfg)
    tool = MultiStoreSearchTool(pgvector_store=pgvector_store)
    stores = {StoreType.PGVECTOR: pgvector_store}
    d = await router.route("zzzzz completely unmatched query", list(stores.keys()))
    # force fallback
    d.fallback_used = True
    d.rankings = []
    results = await router.execute(d, "zzzzz", stores, multistore_tool=tool)
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_perf_fast_path_under_5ms(pgvector_store):
    router = StoreRouter(StoreRouterConfig(cache_size=8))
    stores_keys = [StoreType.PGVECTOR]
    # warm-up
    await router.route("what is an endcap?", stores_keys)
    times_ms = []
    for _ in range(5):
        t0 = time.perf_counter()
        await router.route("what is an endcap?", stores_keys)
        times_ms.append((time.perf_counter() - t0) * 1000)
    times_ms.sort()
    median = times_ms[2]
    assert median < 5.0, f"Fast path median {median:.2f}ms exceeds 5ms budget"


# Additional tests: test_router_with_real_arango, test_router_with_bot_end_to_end
# follow the same fixture-with-skip pattern.
```

---

## Agent Instructions

1. Read the spec (§4 Test Specification → Integration Tests, §5 Acceptance Criteria).
2. Verify all prior FEAT-111 tasks are in `sdd/tasks/completed/`.
3. Inspect existing `packages/ai-parrot/tests/integration/` to match style, fixture patterns, and any available conftest helpers.
4. Write the five scenarios. Skip cleanly when backends are unavailable.
5. Run `pytest packages/ai-parrot/tests/integration/rag/ -v`.
6. Move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*
