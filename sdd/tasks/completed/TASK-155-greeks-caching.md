# TASK-155: Greeks Caching

**Feature**: Multi-Leg Options Strategy Execution (FEAT-023)
**Spec**: `sdd/specs/options-multi-leg-strategies.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (2h)
**Depends-on**: TASK-144
**Assigned-to**: claude-session

---

## Context

> Performance optimization: cache Greeks snapshots to reduce API calls.
> Greeks don't change rapidly; caching for 1-5 minutes is acceptable.

---

## Scope

- Add TTL-based caching for options snapshots
- Cache key: OCC symbol
- Default TTL: 60 seconds (configurable)
- Cache invalidation on position changes
- Use in-memory cache (no Redis dependency)

**NOT in scope**: Distributed caching, persistence.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/alpaca_options.py` | MODIFY | Add caching layer |

---

## Implementation Notes

### Cache Implementation
```python
from functools import lru_cache
from datetime import datetime, timedelta

class GreeksCache:
    def __init__(self, ttl_seconds: int = 60):
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[datetime, dict]] = {}

    def get(self, symbol: str) -> dict | None:
        if symbol in self._cache:
            ts, data = self._cache[symbol]
            if datetime.now() - ts < timedelta(seconds=self.ttl):
                return data
            del self._cache[symbol]
        return None

    def set(self, symbol: str, data: dict) -> None:
        self._cache[symbol] = (datetime.now(), data)

    def invalidate(self, symbol: str) -> None:
        self._cache.pop(symbol, None)
```

---

## Acceptance Criteria

- [x] GreeksCache class implemented with TTL
- [x] `get_options_chain()` uses cache
- [x] `get_position_greeks()` uses cache (via `get_options_positions()`)
- [x] Cache invalidated on order placement
- [x] TTL configurable via constructor
- [x] Cache hit/miss logged at DEBUG level

---

## Completion Note

Implemented `GreeksCache` class in `parrot/finance/tools/alpaca_options.py`:

**Features:**
- TTL-based caching with configurable timeout (default: 60 seconds)
- Cache keyed by OCC option symbol
- Methods: `get()`, `set()`, `invalidate()`, `invalidate_by_underlying()`, `clear()`
- DEBUG level logging for cache hits, misses, expirations, and invalidations

**Integration:**
- `AlpacaOptionsToolkit.__init__()` accepts `greeks_cache_ttl` parameter
- `get_options_chain()` caches each contract's Greeks after API fetch
- `get_options_positions()` checks cache first, only fetches uncached symbols
- Cache invalidated after `place_iron_butterfly()`, `place_iron_condor()`, `close_options_position()`
- Cache cleared in `cleanup()` method

**Tests:**
- Created `tests/test_greeks_cache.py` with 14 tests covering:
  - Basic operations (get, set, invalidate, clear)
  - TTL expiration behavior
  - `invalidate_by_underlying()` functionality
  - Integration scenarios

**Test Results:** 14 new tests passing, 39 existing options toolkit tests passing
