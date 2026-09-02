---
id: F012
query_id: Q011
type: git_log
intent: Recent history on affected modules — fresh regression or latent?
executed_at: 2026-09-02T13:38:40+02:00
duration_ms: 500
parent_id: null
depth: 0
---

# F012 — Not a fresh regression: the seeding + 5 s timeout + kill-on-timeout logic has been unchanged since 2026-07-28

## Summary

`repl_worker/` last touched 2026-08-16 (TASK-2220 config cleanup); the pool/handle semantics date from TASK-1941/1942 (2026-07-27) and the code-review sweep `c7b512a90` (2026-07-28). `pythonpandas.py` seeding was introduced by TASK-1944 (`d6a836e40`, 2026-07-28) and last touched 2026-08-16 (TASK-2218). `pythonrepl.py` last touched 2026-08-20 (CodeQL fixes). Nothing on these paths changed in the 13 days before the report — the failure is environment/timing-triggered, not a code regression.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/`
  excerpt: |
    486bb24bc 2026-08-16 feat(purge-matplotlib-renderer-libs): TASK-2220 — REPL worker & config cleanup
    c7b512a90 2026-07-28 fix(sandbox-hardening): address code-review findings across Modules 1-8
    c84a3c161 2026-07-27 feat(sandbox-hardening): TASK-1942 — WorkerPool prewarm/TTL/ceiling/crash-restart/orphan-reaping
    c4520041e 2026-07-27 feat(sandbox-hardening): TASK-1941 — WorkerHandle deadline SIGKILL enforcement
- path: `packages/ai-parrot/src/parrot/tools/pythonpandas.py`
  excerpt: |
    8008233a8 2026-08-16 feat(purge-matplotlib-renderer-libs): TASK-2218 — Remove matplotlib/seaborn from PythonREPLTool
    c7b512a90 2026-07-28 fix(sandbox-hardening): address code-review findings across Modules 1-8
    d6a836e40 2026-07-28 feat(sandbox-hardening): TASK-1944 — port .locals/.globals call sites to namespace API
- path: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
  excerpt: |
    f2c34cb44 2026-08-20 fix(security): resolve 121 CodeQL code scanning alerts
    8008233a8 2026-08-16 feat(purge-matplotlib-renderer-libs): TASK-2218
