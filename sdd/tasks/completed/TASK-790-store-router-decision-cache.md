# TASK-790: Decision LRU Cache

**Feature**: FEAT-111 — Router-Based Adaptive RAG (Store-Level)
**Spec**: `sdd/specs/router-based-adaptive-rag.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of FEAT-111. The LLM fallback path adds latency and cost; caching routing decisions for identical queries eliminates most of it. `functools.lru_cache` cannot be used on async methods safely, so this task builds a small async-safe LRU over `OrderedDict`.

---

## Scope

- Create `parrot/registry/routing/cache.py` with `class DecisionCache`:
  - Constructor `DecisionCache(maxsize: int)`.
  - `maxsize == 0` → cache is permanently empty; `get` always returns `None`, `put` is a no-op.
  - `async def get(key: str) -> Optional[StoreRoutingDecision]` — returns the cached decision and moves the key to the MRU position.
  - `async def put(key: str, decision: StoreRoutingDecision) -> None` — stores the decision; evicts LRU entry when size exceeds `maxsize`.
  - Uses `asyncio.Lock` to serialize mutations so concurrent requests don't corrupt the `OrderedDict`.
- Provide a helper `build_cache_key(query: str, store_fingerprint: tuple[str, ...]) -> str`:
  - Lowercase the query, collapse whitespace, strip leading/trailing punctuation.
  - Hash with `hashlib.sha1` to keep keys small and stable.
  - Include the sorted `store_fingerprint` so a config change invalidates stale entries.
- Unit tests under `tests/unit/registry/routing/test_cache.py`.

**NOT in scope**: Redis/persistent caching (explicit non-goal in spec §1), cache metrics/telemetry.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/routing/cache.py` | CREATE | `DecisionCache` + `build_cache_key` |
| `packages/ai-parrot/src/parrot/registry/routing/__init__.py` | MODIFY | Re-export `DecisionCache`, `build_cache_key` |
| `packages/ai-parrot/tests/unit/registry/routing/test_cache.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio
import hashlib
from collections import OrderedDict
from typing import Optional

from parrot.registry.routing import StoreRoutingDecision  # from TASK-785
```

### Does NOT Exist
- ~~`functools.lru_cache` on async methods — known to silently misbehave~~ (see spec §7 Known Risks).
- ~~Any existing cache class in `parrot.registry`~~ — none.
- ~~A TTL variant~~ — explicitly out of scope.

---

## Implementation Notes

### Key Constraints
- Use `asyncio.Lock` inside the cache; callers do NOT need to hold a lock externally.
- `OrderedDict.move_to_end(key)` on every successful `get` and on `put` for existing keys.
- Eviction: `popitem(last=False)` removes the LRU entry.
- `build_cache_key`: normalize → hash. Normalization exactly: `re.sub(r"\s+", " ", query.lower().strip())`.
- The cache stores `StoreRoutingDecision` objects; do NOT deep-copy (callers must not mutate returned decisions — document this in a docstring).

### Pattern to Follow
```python
class DecisionCache:
    def __init__(self, maxsize: int) -> None:
        self._maxsize = maxsize
        self._data: OrderedDict[str, StoreRoutingDecision] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[StoreRoutingDecision]: ...
    async def put(self, key: str, decision: StoreRoutingDecision) -> None: ...
```

---

## Acceptance Criteria

- [ ] `from parrot.registry.routing import DecisionCache, build_cache_key` works.
- [ ] `DecisionCache(0)` always returns `None` from `get` and no-ops on `put`.
- [ ] After 257 puts into a `DecisionCache(256)`, only the most-recent 256 remain; the oldest has been evicted.
- [ ] `get` of an existing key promotes it to MRU (subsequent eviction spares it).
- [ ] Concurrent `put`/`get` calls across an `asyncio.gather` do not raise and leave internal state consistent.
- [ ] `build_cache_key("  Hello World  ", ("pgvector",)) == build_cache_key("hello world", ("pgvector",))`.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/unit/registry/routing/test_cache.py -v`.

---

## Test Specification

```python
import asyncio
import pytest
from parrot.registry.routing import (
    DecisionCache, build_cache_key, StoreRoutingDecision, StoreScore,
)
from parrot.tools.multistoresearch import StoreType


def _decision(path="fast"):
    return StoreRoutingDecision(
        rankings=[StoreScore(store=StoreType.PGVECTOR, confidence=0.9)],
        path=path,
    )


@pytest.mark.asyncio
async def test_disabled_cache():
    c = DecisionCache(0)
    await c.put("k", _decision())
    assert await c.get("k") is None


@pytest.mark.asyncio
async def test_put_and_get():
    c = DecisionCache(4)
    await c.put("k", _decision())
    assert (await c.get("k")).path == "fast"


@pytest.mark.asyncio
async def test_lru_eviction():
    c = DecisionCache(2)
    await c.put("a", _decision("a"))
    await c.put("b", _decision("b"))
    await c.put("c", _decision("c"))      # evicts "a"
    assert await c.get("a") is None
    assert await c.get("b") is not None
    assert await c.get("c") is not None


@pytest.mark.asyncio
async def test_get_promotes_to_mru():
    c = DecisionCache(2)
    await c.put("a", _decision("a"))
    await c.put("b", _decision("b"))
    await c.get("a")                      # a is now MRU
    await c.put("c", _decision("c"))      # evicts "b"
    assert await c.get("b") is None
    assert await c.get("a") is not None


@pytest.mark.asyncio
async def test_concurrent_safety():
    c = DecisionCache(10)
    async def worker(i):
        await c.put(f"k{i}", _decision(str(i)))
    await asyncio.gather(*(worker(i) for i in range(50)))
    # should not raise; size bounded
    # exact survivors depend on scheduling, just verify bound
    keys_alive = 0
    for i in range(50):
        if await c.get(f"k{i}"):
            keys_alive += 1
    assert keys_alive <= 10


def test_build_cache_key_normalization():
    k1 = build_cache_key("  Hello   World  ", ("pgvector",))
    k2 = build_cache_key("hello world", ("pgvector",))
    assert k1 == k2


def test_build_cache_key_varies_with_fingerprint():
    k1 = build_cache_key("q", ("pgvector",))
    k2 = build_cache_key("q", ("pgvector", "arango"))
    assert k1 != k2
```

---

## Agent Instructions

1. Read the spec (§3 Module 6, §7 Known Risks — `lru_cache` warning, cache-key normalization spec).
2. Implement the cache and the key helper.
3. Run the test suite.
4. Move this file to `sdd/tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*
