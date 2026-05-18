---
id: F008
query_id: Q016
type: grep
intent: In-memory file-cache patterns (mtime-based or lru_cache) to mirror.
executed_at: 2026-05-18T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F008 — Mtime-based file cache + custom async-safe LRU patterns already in the codebase

## Summary

Two directly-relevant precedents exist. (1) `parrot/stores/kb/local.py`
tracks file freshness via `stat().st_mtime` at lines 180, 195, 248 and
481 — exactly the pattern needed for `AGENT_CONTEXT.md` invalidation.
(2) `parrot/registry/routing/cache.py:3` explicitly notes that
"`functools.lru_cache` silently misbehaves on async methods" and
implements a custom thread/coroutine-safe LRU starting at line 59 — this
is the authoritative pattern when the cache may be touched from async
code. Vanilla `functools.lru_cache` is also used widely for sync helpers
(`auth/resolver.py:140`, `bots/database/toolkits/_crud.py:117`,
`interfaces/database.py:24-69` — four cached helpers). Path matters: a
sync, idempotent file read can use `functools.lru_cache` decorated with
mtime as the cache key; if loaded from inside async code it must use the
async-safe variant.

## Citations

- path: `packages/ai-parrot/src/parrot/stores/kb/local.py`
  lines: 180, 195, 248, 481
  symbol: mtime-based change detection
  excerpt: |
    f.name: f.stat().st_mtime for f in local_files
    ...
    cache_mtime = self.cache_file.stat().st_mtime
    ...
    self._loaded_files[local_file.name] = local_file.stat().st_mtime
    ...
    current_mtime = local_file.stat().st_mtime

- path: `packages/ai-parrot/src/parrot/registry/routing/cache.py`
  lines: 3, 59
  symbol: async-safe LRU
  excerpt: |
    """``functools.lru_cache`` silently misbehaves on async methods — it caches the
    coroutine object, not its result..."""
    ...
    a thread/coroutine-safe LRU without requiring ``functools.lru_cache`` (which
    is sync-only).

- path: `packages/ai-parrot/src/parrot/auth/resolver.py`
  lines: 16, 140
  symbol: lru_cache pattern
  excerpt: |
    from functools import lru_cache
    ...
    self._expand_cached = lru_cache(maxsize=cache_size)(self._expand_roles)

- path: `packages/ai-parrot/src/parrot/bots/database/toolkits/_crud.py`
  lines: 114-129
  symbol: module-level `@lru_cache` builder
  excerpt: |
    @functools.lru_cache(maxsize=None)
    def _build_pydantic_model(...):
        """The function is module-level (not a method) so `functools.lru_cache`
        works..."""

## Notes

Recommend the kb/local.py shape: a tiny private cache dict keyed by
`(path, mtime)` so disk re-read is automatic on file modification, with
the read path being sync (file I/O is fast and the result is reused
across many calls). If the loader must be called from async code,
delegate the read to `asyncio.to_thread()` and use the module-level
`functools.lru_cache` on the sync inner.
