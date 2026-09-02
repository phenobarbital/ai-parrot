---
id: F011
query_id: Q007
type: grep
intent: WorkerConfig defaults and frame-reader error types
executed_at: 2026-09-02T13:38:10+02:00
duration_ms: 400
parent_id: null
depth: 0
---

# F011 — WorkerConfig defaults: 60 s exec deadline, 2 prewarmed spares; no readiness/bootstrap timeout field exists

## Summary

`WorkerConfig` (protocol.py 326-341): `deadline_ms=60_000`, `prewarm_pool_size=2`, `max_workers=0` (→ max(4, cpu) cap 16), `idle_ttl_seconds=1800`, `rlimit_as_bytes=12 GiB`, `rlimit_cpu_seconds=300`. There is **no field for namespace-API timeout or bootstrap grace** — the 5 s in F004 is not configurable. `_read_exact` (365-387) raises `EOFError` with a non-empty message on a closed pipe; `read_frame` (408-429) raises `ValueError` on unknown op. Neither produces an empty-message exception, which rules out worker death as the source of the blank error text (only a timeout does, F017).

## Citations

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py`
  lines: 326-341
  symbol: `WorkerConfig`
  excerpt: |
    rlimit_as_bytes: int = 12 * 1024**3
    rlimit_cpu_seconds: int = 300
    deadline_ms: int = 60_000
    max_workers: int = 0
    idle_ttl_seconds: int = 1800
    prewarm_pool_size: int = 2
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py`
  lines: 365-387
  symbol: `_read_exact`
  excerpt: |
    if not chunk:
        if chunks: raise EOFError("repl_worker protocol: stream closed mid-frame")
        raise EOFError("repl_worker protocol: stream closed")
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py`
  lines: 408-429
  symbol: `read_frame`
