---
id: F003
query_id: Q003
type: read
intent: WorkerPool.acquire / crash-restart / prewarm top-up (log sites pool.py:187/241/265)
executed_at: 2026-09-02T13:37:30+02:00
duration_ms: 900
parent_id: null
depth: 0
---

# F003 — pool.py: a spare is declared "ready" the instant it is spawned

## Summary

`WorkerPool` has **no readiness check anywhere**. `_spawn_handle()` awaits `handle.start()` (which only forks the process, see F004) and `_top_up_prewarmed()` immediately appends it and logs `prewarmed worker ready` (line 187) — the exact log line that appears in the same millisecond as `spawned worker pid=` in the bug report. `acquire()` (214-276) treats `existing.is_alive` (process poll) as the only health signal: a dead worker is logged at 241 and replaced by `self._prewarmed.pop(0)` (264-265) — the *oldest* spare, which in a spiral is the one spawned only one failure-cycle earlier. Nothing in the pool ever pings a worker before handing it out.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py`
  lines: 140-145
  symbol: `WorkerPool._spawn_handle`
  excerpt: |
    handle = WorkerHandle(self._config, output_dir=..., repl_kwargs=..., executor=self._executor)
    await handle.start()
    return handle
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py`
  lines: 166-187
  symbol: `WorkerPool._top_up_prewarmed`
  excerpt: |
    handle = await self._spawn_handle()
    ...
    self._prewarmed.append(handle)
    ...
    logger.debug("WorkerPool: prewarmed worker ready (pool size=%d)", len(self._prewarmed))
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py`
  lines: 231-268
  symbol: `WorkerPool.acquire`
  excerpt: |
    existing = self._sessions.get(session_id)
    if existing is not None:
        if existing.is_alive: ... return existing
        logger.warning("WorkerPool: session %r worker is dead, restarting", session_id)
    ...
    if self._prewarmed:
        handle = self._prewarmed.pop(0)
        logger.debug("WorkerPool: session %r bound to a prewarmed worker", session_id)
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py`
  lines: 17-21
  symbol: module docstring ("Crash restart")
  excerpt: |
    - **Crash restart**: a session whose worker died gets a fresh one on its
      next ``acquire`` — the *interrupted* call's namespace-loss error was
      already reported by ``WorkerHandle.execute()`` at the time of the crash
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py`
  lines: 189-197
  symbol: `WorkerPool._maintenance_loop`
  excerpt: |
    interval = min(5.0, max(1.0, self._config.idle_ttl_seconds / 10))

## Notes

Crash-restart was designed for a worker that died *during* an `execute()` (whose loss error is a dict, not an exception). It is not designed for a worker that was killed by a namespace-API timeout before it ever answered anything — that case raises (see F004) and is what the report shows.
