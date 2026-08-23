---
id: F008
query_id: Q015
type: read
intent: Find existing HTTP throttling / circuit-breaker / retry infrastructure reusable by the CENDOJ shared client
executed_at: 2026-08-23T00:21:58Z
depth: 1
parent_id: F007
---

# F008 — A reusable CircuitBreaker class exists, but it lives in the compression codec router, not in an HTTP layer

## Summary

`CircuitBreaker` is implemented once in the repo, at
`parrot/tools/compression/budget.py:195`, as part of a "latency budget router + per-codec
circuit breaker" that self-degrades a sustainedly over-budget codec to passthrough. The
class is generic enough in spirit to model the CENDOJ open/closed behaviour the source
describes (§2.5), but it is coupled to the compression use case and there is **no** shared
throttled-HTTP-client abstraction (no semaphore-based pacer, no `Retry-After` honouring
layer) to inherit from. The source's "single shared client, one semaphore per process,
15-min breaker" is therefore new work with one class worth studying, not reusing verbatim.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/compression/budget.py`
  lines: 195
  symbol: `CircuitBreaker`
  excerpt: |
    class CircuitBreaker:

- path: `packages/ai-parrot/src/parrot/tools/compression/budget.py`
  lines: 1-8
  excerpt: |
    """Latency budget router + per-codec circuit breaker (G7, G9).

    Decides, from a cheap size estimate taken BEFORE compressing, whether a
    codec call runs inline, is offloaded to an executor, or is skipped
    entirely (passthrough). A per-codec CircuitBreaker self-degrades a
    sustainedly over-budget codec to passthrough.

## Notes

Only files matching `CircuitBreaker` outside build artifacts: `tools/manager.py` (a comment
referencing the BudgetRouter), `tools/compression/report.py`, `tools/compression/budget.py`
and its test. No HTTP-facing usage.
