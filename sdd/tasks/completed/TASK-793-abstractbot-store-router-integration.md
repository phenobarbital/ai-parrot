# TASK-793: AbstractBot Integration (`configure_store_router` + router-aware `_build_vector_context`)

**Feature**: FEAT-111 — Router-Based Adaptive RAG (Store-Level)
**Spec**: `sdd/specs/router-based-adaptive-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-785, TASK-792
**Assigned-to**: unassigned

---

## Context

Implements **Module 8** of FEAT-111. This task wires the `StoreRouter` into the bot pipeline so every RAG-enabled bot automatically benefits once the router is configured. The unconfigured path MUST remain byte-identical to today's behavior.

---

## Scope

- Modify `parrot/bots/abstract.py`:
  - In `AbstractBot.__init__`, initialize `self._store_router: Optional[StoreRouter] = None` and `self._multi_store_tool: Optional[MultiStoreSearchTool] = None` (the tool instance is optional — only constructed lazily when the `FAN_OUT` policy needs it, OR passed by the caller later).
  - Add `def configure_store_router(self, config: StoreRouterConfig, ontology_resolver: Optional[Any] = None, multi_store_tool: Optional[MultiStoreSearchTool] = None) -> None` — constructs and stores a `StoreRouter`.
  - Modify `_build_vector_context` (`abstract.py:2129`):
    - First line of the method body: `if self._store_router is None or not use_vectors or not self.store: <existing behavior>`.
    - Otherwise: gather the available stores (introspect `self.store`, `self._vector_store`, and any other known store attributes — see Implementation Notes), call `self._store_router.route(question, available_stores, invoke_fn=getattr(self, "invoke", None))`, then `self._store_router.execute(decision, question, stores_dict, multistore_tool=self._multi_store_tool, limit=limit, **search_kwargs)`, then convert the results back into the `Tuple[str, Dict[str, Any]]` shape the existing signature returns.
- Introduce a helper `_build_stores_dict(self) -> dict[StoreType, AbstractStore]` on `AbstractBot` that collects the configured stores into a dict keyed by `StoreType`. Unknown store instances → skipped with DEBUG log. Single-store bots (only `self.store`) work too — best-effort type detection via `isinstance(..., PgVectorStore / FAISSStore / ArangoDBStore)`.
- Write unit tests under `tests/unit/bots/test_abstractbot_store_router.py` that:
  - Prove the unconfigured path is unchanged (mock `self.store` behavior before + after the change — same call pattern).
  - Prove the router-aware path is engaged only when `configure_store_router` has been called.

**NOT in scope**: changing `IntentRouterMixin` (TASK-787 handled that), modifying other bot classes, end-to-end real-store tests (TASK-794).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Add `_store_router`, `configure_store_router`, router-aware `_build_vector_context` branch, `_build_stores_dict` |
| `packages/ai-parrot/tests/unit/bots/test_abstractbot_store_router.py` | CREATE | Regression + integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import Any, Optional, Tuple, Dict
from parrot.registry.routing import (
    StoreRouter, StoreRouterConfig, StoreRoutingDecision,
)
from parrot.tools.multistoresearch import StoreType, MultiStoreSearchTool  # multistoresearch.py:30, 42
from parrot.stores.abstract import AbstractStore                            # stores/abstract.py:17
from parrot.stores.postgres import PgVectorStore
from parrot.stores.arango import ArangoDBStore
try:
    from parrot.stores.faiss_store import FAISSStore
except ImportError:
    FAISSStore = None   # match multistoresearch.py:24-27 pattern
```

### Existing Signatures to Use
```python
# parrot/bots/abstract.py:2129
class AbstractBot(...):
    store: Any   # the legacy single-store attribute

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
```

### Does NOT Exist
- ~~`AbstractBot.configure_store_router`~~ — this task creates it.
- ~~`AbstractBot._store_router`, `AbstractBot._multi_store_tool`~~ — this task creates them.
- ~~`AbstractBot._build_stores_dict`~~ — this task creates it.
- ~~A BotManager-level global store router~~ — out of scope; routers are per-bot.

---

## Implementation Notes

### Backward-compatibility guard
The most important rule for this task: when `self._store_router is None`, `_build_vector_context` must execute exactly the same code path it does today (byte-identical behavior). The regression test `test_unconfigured_path_is_unchanged` locks this in.

### Store detection pattern
```python
def _build_stores_dict(self) -> dict[StoreType, AbstractStore]:
    mapping: dict[StoreType, AbstractStore] = {}
    # legacy single-store attribute
    main = getattr(self, "store", None)
    if main is not None:
        st = _infer_store_type(main)
        if st is not None:
            mapping[st] = main
    # additional attributes (best-effort)
    for attr in ("_vector_store", "vector_store", "_faiss_store", "faiss_store",
                 "_arango_store", "arango_store", "_pgvector_store", "pgvector_store"):
        inst = getattr(self, attr, None)
        if inst is not None:
            st = _infer_store_type(inst)
            if st is not None and st not in mapping:
                mapping[st] = inst
    return mapping

def _infer_store_type(store: Any) -> Optional[StoreType]:
    if isinstance(store, PgVectorStore):
        return StoreType.PGVECTOR
    if ArangoDBStore and isinstance(store, ArangoDBStore):
        return StoreType.ARANGO
    if FAISSStore and isinstance(store, FAISSStore):
        return StoreType.FAISS
    return None
```

### Result adaptation
The router returns `list[SearchResult]`; `_build_vector_context` returns `Tuple[str, Dict[str, Any]]`. Reuse the bot's existing method that formats a list of results into a context string — inspect `self.get_vector_context` (referenced at `abstract.py:2164`) for the existing contract. If there is a pre-existing helper to render a list of `SearchResult` into `(context_str, metadata_dict)`, reuse it. Otherwise, produce a minimal rendering: `"\n\n".join(r.content for r in results)` for the context string, `{"sources": [...]}` for the dict.

### Key Constraints
- Do NOT change the `_build_vector_context` signature.
- Add DEBUG-level logs for: router activation, decision path, chosen stores.
- When `self.invoke` is not present (not every bot implements it) → pass `None` as `invoke_fn` — TASK-792 handles the None case gracefully.
- `configure_store_router` is idempotent: calling it twice replaces the prior router and caches.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/abstract.py:2129` — current `_build_vector_context`
- `packages/ai-parrot/src/parrot/bots/abstract.py:2164` — existing `get_vector_context` call (for result rendering reuse)
- `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py:137` — `configure_router` naming precedent

---

## Acceptance Criteria

- [ ] `from parrot.bots.abstract import AbstractBot` still works (no circular import introduced).
- [ ] Calling `_build_vector_context` on a bot that never called `configure_store_router` produces byte-identical behavior to the pre-change implementation (regression test locks this).
- [ ] Calling `configure_store_router(StoreRouterConfig())` wires `self._store_router`.
- [ ] Subsequent `_build_vector_context` calls hit `StoreRouter.route()` + `StoreRouter.execute()`.
- [ ] Bots with no matching `AbstractStore` subclass attributes still work — `_build_stores_dict` returns `{}`, router's `FAN_OUT` policy gracefully delegates to fallback.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/unit/bots/test_abstractbot_store_router.py -v`.
- [ ] Existing bot tests still pass: `pytest packages/ai-parrot/tests/unit/bots/ -v` — 0 new failures.

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.registry.routing import StoreRouterConfig


@pytest.mark.asyncio
async def test_unconfigured_path_is_unchanged(basic_bot_with_pgvector):
    """When router is not configured, behavior matches baseline exactly."""
    bot = basic_bot_with_pgvector
    assert bot._store_router is None
    # Patch `get_vector_context` to observe the existing call path.
    bot.get_vector_context = AsyncMock(return_value=("ctx", {}))
    ctx, meta = await bot._build_vector_context("q")
    bot.get_vector_context.assert_awaited_once()
    assert ctx == "ctx"


@pytest.mark.asyncio
async def test_configure_store_router_sets_attribute(basic_bot_with_pgvector):
    bot = basic_bot_with_pgvector
    bot.configure_store_router(StoreRouterConfig())
    assert bot._store_router is not None


@pytest.mark.asyncio
async def test_router_path_invoked_when_configured(basic_bot_with_pgvector):
    bot = basic_bot_with_pgvector
    bot.configure_store_router(StoreRouterConfig())
    # Monkeypatch router methods
    bot._store_router.route = AsyncMock(return_value=MagicMock(rankings=[], fallback_used=True, cache_hit=False, path="fast"))
    bot._store_router.execute = AsyncMock(return_value=[])
    await bot._build_vector_context("q")
    bot._store_router.route.assert_awaited_once()
    bot._store_router.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_use_vectors_false_skips_router(basic_bot_with_pgvector):
    bot = basic_bot_with_pgvector
    bot.configure_store_router(StoreRouterConfig())
    ctx, meta = await bot._build_vector_context("q", use_vectors=False)
    assert ctx == ""
    assert meta == {}


def test_build_stores_dict_infers_pgvector(basic_bot_with_pgvector):
    from parrot.tools.multistoresearch import StoreType
    mapping = basic_bot_with_pgvector._build_stores_dict()
    assert StoreType.PGVECTOR in mapping
```

Tests require a `basic_bot_with_pgvector` fixture (new). Prefer a tiny concrete subclass of `AbstractBot` that pre-sets `self.store = MagicMock(spec=PgVectorStore)`.

---

## Agent Instructions

1. Read the spec (§2 Component Diagram, §3 Module 8, §7 Patterns to Follow — especially MRO / no-mixin decision).
2. Verify TASK-785 and TASK-792 artifacts exist on this branch.
3. Re-confirm `_build_vector_context` at `packages/ai-parrot/src/parrot/bots/abstract.py:2129` matches the contract; if it has drifted, update this task's Codebase Contract before editing.
4. Implement the changes with the backward-compat guard as the first statement in the router-aware branch.
5. Run the new tests AND `pytest packages/ai-parrot/tests/unit/bots/ -v` to ensure no regression.
6. Move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*
