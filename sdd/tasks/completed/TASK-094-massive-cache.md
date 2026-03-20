# TASK-094: MassiveToolkit Cache Layer

**Feature**: MassiveToolkit
**Spec**: `sdd/specs/massive-toolkit.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: 4e94bc29-f6c5-41d0-8fd5-63e0967fc976

---

## Context

This task implements the caching layer for MassiveToolkit. Different endpoints have different data freshness requirements — options Greeks change tick-by-tick (15 min TTL) while short interest updates bi-monthly (12 hour TTL). The cache layer manages these per-endpoint TTLs.

Reference: Spec Section 6 "Caching Strategy"

---

## Scope

- Create `MassiveCache` class extending/using existing `ToolCache`
- Implement per-endpoint TTL configuration:
  - Options Chain: 15 min (900s)
  - Short Interest: 12 hours (43200s)
  - Short Volume: 6 hours (21600s)
  - Earnings: 24 hours (86400s)
  - Analyst Ratings: 4 hours (14400s)
- Implement cache key generation that includes all relevant parameters
- Implement `get()`, `set()`, `invalidate()` methods

**NOT in scope**:
- Client implementation (TASK-093)
- Toolkit class (TASK-095)
- Cache warming strategies

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/massive/cache.py` | CREATE | Cache layer with per-endpoint TTLs |

---

## Implementation Notes

### Pattern to Follow

```python
# Reference: parrot/tools/cache.py
from parrot.tools.cache import ToolCache, DEFAULT_TOOL_CACHE_TTL

class MassiveCache:
    """Cache layer for MassiveToolkit with per-endpoint TTLs."""

    # TTLs by endpoint
    TTLS = {
        "options_chain": 900,       # 15 minutes
        "short_interest": 43200,    # 12 hours
        "short_volume": 21600,      # 6 hours
        "earnings": 86400,          # 24 hours
        "analyst_ratings": 14400,   # 4 hours
    }

    def __init__(self, redis_client=None):
        self._cache = ToolCache(redis_client=redis_client)
        self.logger = logging.getLogger(__name__)

    def _make_key(self, endpoint: str, **params) -> str:
        """Generate cache key from endpoint and parameters."""
        param_str = ":".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
        return f"massive:{endpoint}:{param_str}"

    async def get(self, endpoint: str, **params) -> dict | None:
        """Get cached result for endpoint with given parameters."""
        key = self._make_key(endpoint, **params)
        return await self._cache.get(key)

    async def set(self, endpoint: str, data: dict, **params) -> None:
        """Cache result with endpoint-specific TTL."""
        key = self._make_key(endpoint, **params)
        ttl = self.TTLS.get(endpoint, DEFAULT_TOOL_CACHE_TTL)
        await self._cache.set(key, data, ttl=ttl)
```

### Key Constraints

- Must work with existing `ToolCache` infrastructure
- Cache keys must be unique per endpoint + parameters combination
- Handle None/missing parameters gracefully (don't include in key)
- Log cache hits/misses at DEBUG level

### References in Codebase

- `parrot/tools/cache.py` — Base `ToolCache` class
- `parrot/tools/finnhub.py` — Caching pattern in existing toolkit

---

## Acceptance Criteria

- [ ] `MassiveCache` class implemented with all 5 endpoint TTLs
- [ ] Cache key generation includes all non-None parameters
- [ ] `get()` returns None for cache miss, dict for hit
- [ ] `set()` uses correct TTL per endpoint
- [ ] No linting errors: `ruff check parrot/tools/massive/`
- [ ] Importable: `from parrot.tools.massive.cache import MassiveCache`

---

## Test Specification

```python
# tests/test_massive_cache.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.tools.massive.cache import MassiveCache


@pytest.fixture
def mock_tool_cache():
    """Mock the underlying ToolCache."""
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    return cache


class TestMassiveCache:
    def test_cache_key_generation(self):
        """Keys are unique per endpoint and params."""
        cache = MassiveCache()
        key1 = cache._make_key("options_chain", underlying="AAPL", limit=100)
        key2 = cache._make_key("options_chain", underlying="AAPL", limit=200)
        key3 = cache._make_key("short_interest", symbol="AAPL")

        assert key1 != key2  # Different limit
        assert key1 != key3  # Different endpoint

    def test_cache_key_ignores_none(self):
        """None parameters excluded from key."""
        cache = MassiveCache()
        key1 = cache._make_key("options_chain", underlying="AAPL", contract_type=None)
        key2 = cache._make_key("options_chain", underlying="AAPL")
        assert key1 == key2

    @pytest.mark.asyncio
    async def test_ttl_per_endpoint(self, mock_tool_cache):
        """Each endpoint uses correct TTL."""
        cache = MassiveCache(redis_client=mock_tool_cache)
        cache._cache = mock_tool_cache

        await cache.set("options_chain", {"data": "test"}, underlying="AAPL")
        mock_tool_cache.set.assert_called_once()
        call_args = mock_tool_cache.set.call_args
        assert call_args.kwargs.get("ttl") == 900  # 15 min

        mock_tool_cache.set.reset_mock()
        await cache.set("short_interest", {"data": "test"}, symbol="GME")
        call_args = mock_tool_cache.set.call_args
        assert call_args.kwargs.get("ttl") == 43200  # 12 hours
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/massive-toolkit.spec.md` for TTL details
2. **Check dependencies** — none for this task
3. **Read** `parrot/tools/cache.py` to understand existing `ToolCache`
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** the cache layer in `parrot/tools/massive/cache.py`
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-094-massive-cache.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: 4e94bc29-f6c5-41d0-8fd5-63e0967fc976
**Date**: 2026-03-02
**Notes**: All 24 unit tests pass. Ruff clean. Import verified. Implementation includes `get()`, `set()`, `invalidate()`, `invalidate_endpoint()`, and `close()` methods with 6 per-endpoint TTLs (options_chain=900s, short_interest=43200s, short_volume=21600s, earnings=86400s, analyst_ratings=14400s, consensus_ratings=14400s).

**Deviations from spec**: Added `consensus_ratings` TTL (4h) and `invalidate_endpoint()` bulk invalidation method beyond the original scope — both are useful additions that don't break any contract.
