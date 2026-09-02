---
id: F001
query_id: Q001
type: wiki_query
intent: Orient — where WorkerPool / prewarm / crash-restart live, plus spec/tasks/tests
executed_at: 2026-09-02T13:37:00+02:00
duration_ms: 4200
parent_id: null
depth: 0
---

# F001 — Wiki orientation: repl_worker pool subsystem

## Summary

12 pages. The subsystem is FEAT-380 "Sandbox Hardening": `pool.py` (Module 4, TASK-1942), `handle.py` (Module 3, TASK-1941), `worker.py` (Module 2, TASK-1940), tests under `packages/ai-parrot/tests/repl_worker/`, docs in `docs/repl-worker-sandbox.md`, spec `sdd/specs/sandbox-hardening.spec.md`.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/pool.py`
  wiki_page_id: file:packages/ai-parrot/src/parrot/tools/repl_worker/pool.py (score=0.95)
  symbol: `WorkerPool`
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
  wiki_page_id: file:packages/ai-parrot/src/parrot/tools/repl_worker/handle.py (score=0.10)
  symbol: `WorkerHandle`
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py`
  wiki_page_id: file:packages/ai-parrot/src/parrot/tools/repl_worker/worker.py (score=0.09)
- path: `packages/ai-parrot/tests/repl_worker/test_pool.py`
  wiki_page_id: file:packages/ai-parrot/tests/repl_worker/test_pool.py (score=0.78)
- path: `packages/ai-parrot/tests/repl_worker/test_integration.py`
  wiki_page_id: file:packages/ai-parrot/tests/repl_worker/test_integration.py (score=0.39)
- path: `docs/repl-worker-sandbox.md`
  wiki_page_id: file:docs/repl-worker-sandbox.md (score=0.11)
- path: `sdd/specs/sandbox-hardening.spec.md`
  wiki_page_id: file:sdd/specs/sandbox-hardening.spec.md (score=0.03)
- path: `sdd/tasks/completed/TASK-1942-repl-worker-pool-lifecycle.md`
  wiki_page_id: file:sdd/tasks/completed/TASK-1942-repl-worker-pool-lifecycle.md (score=1.00)
