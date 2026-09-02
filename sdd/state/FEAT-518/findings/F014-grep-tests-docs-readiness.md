---
id: F014
query_id: Q013
type: grep
intent: Any readiness handshake / cold-start coverage in tests, docs, spec? Is ping() used?
executed_at: 2026-09-02T13:41:20+02:00
duration_ms: 900
parent_id: null
depth: 0
---

# F014 — `ping()` is dead code; the only cold-start awareness is a test comment about `deadline_ms`

## Summary

`WorkerHandle.ping` has **zero callers** in `packages/ai-parrot/src/parrot` (all `.ping(` hits are Redis). `tests/repl_worker/test_integration.py:135-160` (`test_e2e_runaway_loop_recovery`) documents that "`deadline_ms` must cover the freshly-spawned worker's own pandas/numpy bootstrap … too tight a deadline would time out the FIRST call on cold start" — the authors knew the cold-start hazard for `execute()` but the same reasoning was never applied to the 5 s namespace API. No test exercises `set_var`/`list_vars` against a *cold* worker under load; `test_handle.py:135-151` and `test_integration.py:123-129` call them only after a successful `execute`. `docs/repl-worker-sandbox.md:132` describes prewarmed spares as having "pandas/numpy already imported" (1–3 s import cost) — an assumption the pool never verifies (F003). Spec AC10 (`sandbox-hardening.spec.md:464`) only requires that the first execution not pay the import cost.

## Citations

- path: `packages/ai-parrot/tests/repl_worker/test_integration.py`
  lines: 135-160
  symbol: `TestE2E.test_e2e_runaway_loop_recovery`
  excerpt: |
    `deadline_ms` must cover the freshly-spawned (not prewarmed) worker's
    own pandas/numpy bootstrap too, since that runs before it
    can process the first `exec` request — too tight a deadline would
    time out the FIRST ("z = 5") call on cold start
    config = WorkerConfig(deadline_ms=4_000, max_workers=2, idle_ttl_seconds=30, prewarm_pool_size=0)
- path: `packages/ai-parrot/tests/repl_worker/test_handle.py`
  lines: 135-151
  symbol: `test_get_set_var_round_trip` / `test_list_vars_and_snapshot`
- path: `packages/ai-parrot/tests/repl_worker/test_pool.py`
  lines: 69-144
  symbol: pool lifecycle tests (only `is_alive` assertions, no readiness)
- path: `docs/repl-worker-sandbox.md`
  lines: 132
  excerpt: |
    | `prewarm_pool_size` | `2` | Idle, pre-booted spare workers (pandas/numpy already imported …) kept ready so a session's first call doesn't pay the 1–3s import cost. |
- path: `docs/repl-worker-sandbox.md`
  lines: 142
  excerpt: |
    can crash the worker **during its own bootstrap** (numpy/pandas import),
- path: `sdd/specs/sandbox-hardening.spec.md`
  lines: 464
  symbol: AC10
