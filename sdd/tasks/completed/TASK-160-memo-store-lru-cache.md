# TASK-160: MemoStore LRU Cache

**Feature**: Investment Memo Persistency (FEAT-024)
**Spec**: `sdd/specs/finance-investment-memo-persistency.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1h)
**Depends-on**: TASK-159
**Assigned-to**: claude-session

---

## Context

> In-memory LRU cache for frequently accessed memos.
> Reduces filesystem reads for recently accessed memos.

---

## Scope

- Add LRU cache logic to `FileMemoStore`
- Implement cache eviction when size exceeds limit
- Cache memos on `store()` and `get()`
- Move recently accessed items to end (LRU order)
- Use `collections.OrderedDict` or manual dict tracking

**NOT in scope**: Distributed caching, Redis backend.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/memo_store/file_store.py` | MODIFY | Add LRU cache logic |

---

## Acceptance Criteria

- [x] Cache limited to `cache_size` entries (default 100)
- [x] Oldest entries evicted when cache full (LRU policy)
- [x] Cache hit returns memo without filesystem read
- [x] Recently accessed entries move to end
- [x] Thread-safe cache operations (async lock)
- [x] Read latency < 50ms for cached memos

---

## Completion Note

**Completed**: 2026-03-04

### Implementation Summary

Upgraded `FileMemoStore._cache` from plain `dict` to `OrderedDict` with proper LRU semantics:

1. **Import**: Added `from collections import OrderedDict`
2. **Type**: Changed `_cache: dict[str, Any]` → `_cache: OrderedDict[str, Any]`
3. **Added `_cache_put_locked(memo_id, memo)`**:
   - If entry exists: `move_to_end()` + update value
   - If new: insert + evict oldest with `popitem(last=False)` while over limit
4. **Added `_cache_get_locked(memo_id)`**:
   - On hit: `move_to_end()` to refresh recency, return cached memo
   - On miss: return `None`
5. **Updated `store()`**: calls `_cache_put_locked()` instead of direct dict assignment
6. **Updated `get()`**: calls `_cache_get_locked()` instead of plain dict lookup
7. **Updated `_load_from_disk()`**: calls `_cache_put_locked()` on successful load

Both helpers are marked "must be called while holding `self._lock`" — all callers already hold the lock.

### Test Results
- Cache capped at cache_size entries ✓
- AAPL evicted when 4th entry added (cache_size=3) ✓
- MSFT retained after explicit `get()` access before eviction ✓
- TSLA evicted (LRU, not recently accessed) ✓
- Cache miss correctly falls back to disk ✓
- All linting checks pass ✓
